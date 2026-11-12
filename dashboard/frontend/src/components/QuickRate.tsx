import { useCallback, useEffect, useState } from 'react'
import { BellRing, CheckCircle2 } from 'lucide-react'
import { api, errorMessage } from '../api'
import { useLive } from '../live'
import { ageSeconds, relative } from '../format'
import { Card, cx } from './ui'
import type { FeedbackItem, MlStatus } from '../types'

const LABELS = ['Very uncomfortable', 'Uncomfortable', 'Neutral', 'Comfortable', 'Very comfortable']
const NUDGE_AFTER_S = 3600

export default function QuickRate() {
  const { reading, now } = useLive()
  const [status, setStatus] = useState<MlStatus | null>(null)
  const [lastAt, setLastAt] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, f] = await Promise.all([
        api<MlStatus>('/ml/status'),
        api<{ items: FeedbackItem[] }>('/feedback?limit=1'),
      ])
      setStatus(s)
      setLastAt(f.items[0]?.created_at ?? null)
    } catch {
      // overview works without it
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const rate = async (value: number) => {
    setBusy(value)
    setError(null)
    setSaved(null)
    try {
      const res = await api<{ context_simulated: boolean }>('/feedback', {
        method: 'POST',
        body: { rating: value, device_id: reading?.device_id ?? null },
      })
      setSaved(res.context_simulated ? 'Saved, but on simulated data so it is not used for training.' : `Saved: ${LABELS[value - 1]?.toLowerCase()}.`)
      void load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const since = ageSeconds(lastAt, now)
  const nudge = since === null || since > NUDGE_AFTER_S
  const usable = status?.usable_feedback ?? 0
  const needed = status?.min_labels ?? 30
  const days = status?.usable_sessions ?? 0
  const neededDays = status?.min_sessions ?? 2

  return (
    <Card title="How does the room feel?" subtitle="Each rating teaches your comfort model">
      <div className="grid grid-cols-5 gap-2" role="group" aria-label="Comfort rating, 1 to 5">
        {LABELS.map((label, i) => (
          <button
            key={label}
            type="button"
            title={label}
            aria-label={`${i + 1}: ${label}`}
            disabled={busy !== null || !reading}
            onClick={() => void rate(i + 1)}
            className={cx(
              'flex h-11 items-center justify-center rounded-xl border border-line text-lg font-bold transition-colors hover:bg-raised',
              'disabled:cursor-not-allowed disabled:opacity-50',
              busy === i + 1 && 'border-accent bg-accent text-accent-ink',
            )}
          >
            {i + 1}
          </button>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-muted">
        <span>Very uncomfortable</span>
        <span>Very comfortable</span>
      </div>

      {saved && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-good-ink" role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {saved}
        </p>
      )}
      {error && <p className="mt-3 text-sm text-danger-ink" role="alert">{error}</p>}
      {!saved && !error && nudge && reading && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-warn-ink">
          <BellRing className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {lastAt ? 'No rating in the last hour. How is it now?' : 'No ratings yet. Rate a few times a day in different conditions.'}
        </p>
      )}

      <dl className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-xl bg-raised/60 px-2 py-2">
          <dt className="text-muted">Ratings</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular">{usable} / {needed}</dd>
        </div>
        <div className="rounded-xl bg-raised/60 px-2 py-2">
          <dt className="text-muted">Days</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular">{days} / {neededDays}</dd>
        </div>
        <div className="rounded-xl bg-raised/60 px-2 py-2">
          <dt className="text-muted">Last</dt>
          <dd className="mt-0.5 text-sm font-semibold">{relative(since)}</dd>
        </div>
      </dl>
    </Card>
  )
}
