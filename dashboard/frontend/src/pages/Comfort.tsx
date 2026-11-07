import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { CheckCircle2, Droplets, Info, Lightbulb, Smile, Sun, Thermometer } from 'lucide-react'
import { api, errorMessage } from '../api'
import { useLive, usePrimaryDevice } from '../live'
import { localTime, num } from '../format'
import { DataSourceBadge } from '../components/status'
import { Badge, Button, Card, cx, EmptyState, ErrorNote, IconBubble, PageHeader, ProgressRing, Skeleton, type Hue } from '../components/ui'
import type { Advice, FeedbackItem, MlStatus } from '../types'

const SCALE = [
  { value: 1, label: 'Very uncomfortable' },
  { value: 2, label: 'Uncomfortable' },
  { value: 3, label: 'Neutral' },
  { value: 4, label: 'Comfortable' },
  { value: 5, label: 'Very comfortable' },
]

const TONE = {
  good: 'bg-good/15 text-good-ink',
  warn: 'bg-warn/15 text-warn-ink',
  neutral: 'bg-raised text-ink-2',
} as const

function rangeWord(v: number | null, lo: number, hi: number, low: string, high: string): { word: string; tone: 'good' | 'warn' | 'neutral' } {
  if (v === null) return { word: '—', tone: 'neutral' }
  if (v < lo) return { word: low, tone: 'warn' }
  if (v > hi) return { word: high, tone: 'warn' }
  return { word: 'Good', tone: 'good' }
}

export default function Comfort() {
  const { reading } = useLive()
  const device = usePrimaryDevice()
  const [advice, setAdvice] = useState<Advice | null>(null)
  const [status, setStatus] = useState<MlStatus | null>(null)
  const [history, setHistory] = useState<FeedbackItem[]>([])
  const [rating, setRating] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [a, s, f] = await Promise.all([
        api<Advice>('/ml/advice'),
        api<MlStatus>('/ml/status'),
        api<{ items: FeedbackItem[] }>('/feedback?limit=10'),
      ])
      setAdvice(a)
      setStatus(s)
      setHistory(f.items)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, reading?.id])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (rating === null) return
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      const res = await api<{ id: number; context_simulated: boolean }>('/feedback', {
        method: 'POST',
        body: { rating, device_id: reading?.device_id ?? null, note: note.trim() || null },
      })
      setSaved(
        res.context_simulated
          ? 'Saved. Note: it was attached to simulated data, so it will not be used for training.'
          : 'Thanks, your rating was saved with the current conditions.',
      )
      setRating(null)
      setNote('')
      void load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const conditions: { label: string; hue: Hue; icon: ReactNode; value: string; status: { word: string; tone: 'good' | 'warn' | 'neutral' } }[] = reading
    ? [
        {
          label: 'Temperature',
          hue: 'temp',
          icon: <Thermometer className="h-4 w-4" aria-hidden />,
          value: `${num(reading.temperature_c)} °C`,
          status: rangeWord(reading.temperature_c, 20, 26, 'Cool', 'Warm'),
        },
        {
          label: 'Humidity',
          hue: 'hum',
          icon: <Droplets className="h-4 w-4" aria-hidden />,
          value: `${num(reading.humidity_pct, 0)} %`,
          status: rangeWord(reading.humidity_pct, 30, 60, 'Dry', 'Humid'),
        },
        {
          label: 'Light',
          hue: 'lux',
          icon: <Sun className="h-4 w-4" aria-hidden />,
          value: `${num(reading.light_pct, 0)} %`,
          status:
            reading.light_pct === null
              ? { word: '—', tone: 'neutral' }
              : reading.light_pct < 30
                ? { word: 'Dim', tone: 'neutral' }
                : { word: 'Bright', tone: 'good' },
        },
      ]
    : []

  const hasModel = advice?.basis === 'model' && typeof advice.estimate === 'number'
  const usable = status?.usable_feedback ?? 0
  const needed = status?.min_labels ?? 30

  return (
    <>
      <PageHeader
        title="Comfort advisor"
        subtitle="Your ratings teach SmartBuddy what comfortable means for you."
        action={<DataSourceBadge reading={reading} device={device} />}
      />
      {error && <div className="mb-4"><ErrorNote>{error}</ErrorNote></div>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Current conditions" subtitle={reading ? `Updated ${localTime(reading.received_at)}` : undefined}>
          {!reading ? (
            <EmptyState title="No conditions to show yet" />
          ) : (
            <ul className="space-y-3">
              {conditions.map((c) => (
                <li key={c.label} className="flex items-center gap-3 rounded-2xl bg-raised/60 px-3 py-2.5">
                  <IconBubble hue={c.hue} size="sm">{c.icon}</IconBubble>
                  <div className="flex-1">
                    <div className="text-xs text-muted">{c.label}</div>
                    <div className="text-lg font-semibold tabular">{c.value}</div>
                  </div>
                  <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', TONE[c.status.tone])}>{c.status.word}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={hasModel ? 'Comfort estimate' : 'Personal model'} subtitle={hasModel ? `Model ${advice?.model_version}` : 'Collecting ratings for training'}>
          <div className="flex flex-col items-center py-2 text-center">
            {advice === null ? (
              <Skeleton className="h-[148px] w-[148px] rounded-full" />
            ) : hasModel ? (
              <ProgressRing value={((advice!.estimate as number) - 1) / 4} size={148} colorClass="text-good">
                <span className="text-3xl font-bold tabular">{(advice!.estimate as number).toFixed(1)}</span>
                <span className="text-xs text-muted">out of 5</span>
              </ProgressRing>
            ) : (
              <ProgressRing value={usable / needed} size={148}>
                <span className="text-3xl font-bold tabular">{usable}</span>
                <span className="text-xs text-muted">of {needed} ratings</span>
              </ProgressRing>
            )}
            <p className="mt-4 font-semibold">
              {hasModel ? SCALE[Math.min(4, Math.max(0, Math.round(advice!.estimate as number) - 1))]?.label : 'No model yet'}
            </p>
            <p className="mt-1 max-w-[16rem] text-sm text-muted">
              {hasModel
                ? 'Estimated from your own past ratings in similar conditions.'
                : `Training needs at least ${needed} real ratings from ${status?.min_sessions ?? 2}+ separate days.`}
            </p>
          </div>
        </Card>

        <Card title="How comfortable is it?" subtitle="Rate how the room feels to you right now.">
          <form onSubmit={submit}>
            <fieldset>
              <legend className="sr-only">Comfort rating, 1 to 5</legend>
              <div className="grid grid-cols-5 gap-2">
                {SCALE.map((s) => (
                  <label
                    key={s.value}
                    className={cx(
                      'flex cursor-pointer flex-col items-center gap-1 rounded-2xl border px-1 py-3 text-center transition-colors',
                      rating === s.value ? 'border-accent bg-accent text-accent-ink shadow-sm' : 'border-line hover:bg-raised',
                    )}
                    title={s.label}
                  >
                    <input type="radio" name="rating" value={s.value} checked={rating === s.value} onChange={() => setRating(s.value)} className="sr-only" />
                    <span className="text-xl font-bold">{s.value}</span>
                  </label>
                ))}
              </div>
              <div className="mt-2 flex justify-between text-xs text-muted">
                <span>Very uncomfortable</span>
                <span>Very comfortable</span>
              </div>
            </fieldset>
            <label className="mt-4 block text-sm font-medium" htmlFor="note">Note <span className="font-normal text-muted">(optional)</span></label>
            <input
              id="note"
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. just came back from a walk"
              className="mt-1.5 h-11 w-full rounded-xl border border-line bg-surface px-3.5 text-sm placeholder:text-muted focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/15"
            />
            <Button type="submit" variant="primary" className="mt-4 w-full" busy={busy} disabled={rating === null || !reading}>
              <Smile className="h-4 w-4" aria-hidden />
              Save rating{rating !== null ? ` (${SCALE[rating - 1]?.label.toLowerCase()})` : ''}
            </Button>
            {saved && (
              <p className="mt-3 flex items-start gap-1.5 text-sm text-good-ink" role="status">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {saved}
              </p>
            )}
          </form>
        </Card>
      </div>

      <Card
        className="mt-6"
        title="Recommendations"
        action={
          advice?.available ? (
            advice.basis === 'model' ? <Badge tone="accent">Personal model {advice.model_version}</Badge> : <Badge>General guidance - no model yet</Badge>
          ) : undefined
        }
      >
        {advice === null ? (
          <Skeleton className="h-20" />
        ) : !advice.available ? (
          <p className="text-ink-2">{advice.reason}</p>
        ) : (
          <>
            <p className="text-lg font-semibold">{advice.headline}</p>
            <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
              {advice.tips?.map((t) => (
                <li key={t} className="flex items-start gap-3 rounded-2xl bg-raised/60 px-3.5 py-3 text-sm text-ink-2">
                  <IconBubble hue="lux" size="sm"><Lightbulb className="h-4 w-4" aria-hidden /></IconBubble>
                  <span className="pt-1">{t}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 flex items-start gap-1.5 text-xs text-muted">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {advice.disclaimer}
              {advice.based_on_simulated_data && ' Based on simulated test data.'}
            </p>
          </>
        )}
      </Card>

      <Card className="mt-6" title="Recent ratings" subtitle={`${usable} usable for training`}>
        {history.length === 0 ? (
          <EmptyState title="No ratings yet">Ratings appear here with the conditions they were given in.</EmptyState>
        ) : (
          <div className="-mx-5 overflow-x-auto sm:-mx-6">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead>
                <tr className="border-y border-line bg-raised/60 text-xs uppercase tracking-wide text-muted">
                  <th className="px-5 py-3 font-semibold sm:px-6">When</th>
                  <th className="px-3 py-3 font-semibold">Rating</th>
                  <th className="px-3 py-3 text-right font-semibold">Temp °C</th>
                  <th className="px-3 py-3 text-right font-semibold">Humidity %</th>
                  <th className="px-3 py-3 text-right font-semibold">Light %</th>
                  <th className="px-5 py-3 font-semibold sm:px-6">Note</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {history.map((f) => (
                  <tr key={f.id} className="border-b border-line/70 last:border-0 hover:bg-raised/50">
                    <td className="whitespace-nowrap px-5 py-3 sm:px-6">{localTime(f.created_at)}</td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-2">
                        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/15 text-sm font-bold text-accent">{f.rating}</span>
                        {SCALE[f.rating - 1]?.label}
                        {f.context_simulated && <Badge tone="accent">simulated</Badge>}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right font-medium">{num(f.temperature_c)}</td>
                    <td className="px-3 py-3 text-right font-medium">{num(f.humidity_pct, 0)}</td>
                    <td className="px-3 py-3 text-right font-medium">{num(f.light_pct, 0)}</td>
                    <td className="px-5 py-3 text-ink-2 sm:px-6">{f.note ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
