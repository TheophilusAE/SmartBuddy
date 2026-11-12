import { useState } from 'react'
import { Play } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, errorMessage } from '../api'
import { localTime } from '../format'
import { Badge, Button, Card, cx, ErrorNote } from './ui'
import type { ForecastResult } from '../types'

const NAMES: Record<string, string> = {
  persistence: 'Baseline (no change)',
  linear: 'Linear regression',
  random_forest: 'Random forest',
}
const TARGET_NAMES: Record<string, string> = { temperature_c: 'Temperature (°C)', humidity_pct: 'Humidity (%)' }

function statusText(s?: string) {
  if (s === 'deployed') return 'Deployed'
  if (s === 'no_improvement') return 'Did not beat baseline'
  if (s === 'insufficient_data') return 'Not enough data'
  return 'Never run'
}

function Metrics({ result }: { result: ForecastResult }) {
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-6">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead>
          <tr className="border-y border-line bg-raised/60 text-xs uppercase tracking-wide text-muted">
            <th className="px-5 py-3 font-semibold sm:px-6">Target / model</th>
            <th className="px-3 py-3 text-right font-semibold">MAE</th>
            <th className="px-3 py-3 text-right font-semibold">RMSE</th>
            <th className="px-5 py-3 text-right font-semibold sm:px-6">vs baseline</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {Object.entries(result.metrics ?? {}).flatMap(([target, models]) => {
            const base = models.persistence
            return Object.entries(models).map(([name, m]) => {
              const delta = base && name !== 'persistence' ? ((m.mae - base.mae) / base.mae) * 100 : null
              const used = result.beats_baseline?.[target] && result.best_candidate?.[target] === name
              return (
                <tr key={`${target}-${name}`} className="border-b border-line/70 last:border-0">
                  <td className="px-5 py-2.5 sm:px-6">
                    <span className="text-muted">{TARGET_NAMES[target] ?? target} · </span>
                    <span className="font-medium">{NAMES[name] ?? name}</span>
                    {used && <span className="ml-2"><Badge tone="accent">used</Badge></span>}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold">{m.mae.toFixed(3)}</td>
                  <td className="px-3 py-2.5 text-right">{m.rmse.toFixed(3)}</td>
                  <td className={cx('px-5 py-2.5 text-right font-medium sm:px-6', delta !== null && delta < 0 ? 'text-good-ink' : delta !== null ? 'text-danger-ink' : 'text-muted')}>
                    {delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}%`}
                  </td>
                </tr>
              )
            })
          })}
        </tbody>
      </table>
      <p className="mt-3 px-5 text-xs text-muted sm:px-6">
        Lower is better. Errors are in °C or % on the held-out (later) part of the recordings. A target that doesn't beat
        the baseline falls back to "no change".
      </p>
    </div>
  )
}

function SeriesChart({ points }: { points: NonNullable<ForecastResult['test_series']> }) {
  const data = points.map((p) => ({ ...p, label: new Date(p.at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }))
  return (
    <figure>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="var(--chart-grid)" />
            <XAxis dataKey="label" tick={{ fill: 'var(--chart-label)', fontSize: 11 }} stroke="var(--chart-axis)" minTickGap={24} />
            <YAxis domain={['auto', 'auto']} tick={{ fill: 'var(--chart-label)', fontSize: 11 }} stroke="var(--chart-axis)" width={48} />
            <Tooltip isAnimationActive={false} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line type="monotone" dataKey="actual" name="Actual (later)" stroke="var(--chart-label)" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line type="monotone" dataKey="predicted" name="ML prediction" stroke="rgb(var(--c-accent))" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line type="monotone" dataKey="now" name="Baseline (no change)" stroke="var(--chart-axis)" strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-xs text-muted">
        Temperature on the held-out period. Each point compares the forecast made then with what the sensor actually read
        later.
      </figcaption>
    </figure>
  )
}

export default function ForecastEvaluation({
  deployed,
  last,
  isAdmin,
  onTrained,
}: {
  deployed: ForecastResult | null
  last: ForecastResult | null
  isAdmin: boolean
  onTrained: () => void
}) {
  const [horizon, setHorizon] = useState(5)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const shown = deployed ?? (last && last.metrics ? last : null)

  const train = async () => {
    setBusy(true)
    setNote(null)
    setError(null)
    try {
      const res = await api<ForecastResult>(`/ml/forecast/train?horizon=${horizon}`, { method: 'POST' })
      setNote(res.status === 'deployed' ? `Deployed ${res.model_version}.` : res.message ?? statusText(res.status))
      onTrained()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mt-10">
      <h2 className="text-xl font-semibold">Room forecast model</h2>
      <p className="mt-1 text-sm text-muted">
        Predicts temperature and humidity a few minutes ahead from your own sensor readings. No ratings needed.
      </p>
      {error && <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>}

      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Status" subtitle={deployed ? `Model ${deployed.model_version}` : 'No forecast deployed'}>
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted">Last training</dt>
            <dd className="text-right font-medium">{statusText(last?.status)}</dd>
            <dt className="text-muted">When</dt>
            <dd className="text-right">{last ? localTime(last.attempted_at) : '—'}</dd>
            <dt className="text-muted">Horizon</dt>
            <dd className="text-right tabular">{shown ? `${shown.horizon_min} min` : '—'}</dd>
            <dt className="text-muted">Readings used</dt>
            <dd className="text-right tabular">{last ? last.summary.readings.toLocaleString() : '—'}</dd>
            <dt className="text-muted">Hours recorded</dt>
            <dd className="text-right tabular">{last ? last.summary.hours_recorded : '—'}</dd>
            <dt className="text-muted">Samples</dt>
            <dd className="text-right tabular">{last ? last.summary.samples : '—'}</dd>
          </dl>
          {last?.message && <p className="mt-3 text-sm text-ink-2">{last.message}</p>}
          {isAdmin && (
            <div className="mt-5">
              <label className="text-xs font-semibold uppercase tracking-wide text-muted" htmlFor="horizon">Minutes ahead</label>
              <select
                id="horizon"
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                className="mt-1.5 h-10 w-full rounded-xl border border-line bg-surface px-3 text-sm"
              >
                {[5, 10, 15, 30].map((m) => <option key={m} value={m}>{m} min</option>)}
              </select>
              <Button variant="primary" className="mt-3 w-full" busy={busy} onClick={() => void train()}>
                <Play className="h-4 w-4" aria-hidden />
                Train forecast
              </Button>
              <p className="mt-2 text-xs text-muted">Longer horizons need longer continuous recordings.</p>
              {note && <p className="mt-2 text-sm font-medium" role="status">{note}</p>}
            </div>
          )}
        </Card>

        <Card className="lg:col-span-2" title="Model comparison" subtitle={shown?.split?.method}>
          {shown ? <Metrics result={shown} /> : <p className="text-sm text-muted">No metrics yet. Train the forecast first.</p>}
        </Card>
      </div>

      {shown && (
        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="Forecast vs actual" subtitle={shown.split ? `${localTime(shown.split.test_from)} – ${localTime(shown.split.test_to)}` : undefined}>
            {shown.test_series?.length ? <SeriesChart points={shown.test_series} /> : <p className="text-sm text-muted">No test series stored.</p>}
          </Card>
          <Card title="Method and limitations">
            {shown.split && (
              <p className="text-sm text-ink-2">
                {shown.split.train_rows} training samples and {shown.split.test_rows} test samples, from{' '}
                {shown.summary.hours_recorded} h of recordings ({shown.summary.segments} continuous runs). Features: last
                temperature, humidity, light, their 1 and 5 minute changes, fan state and recent motion.
                {shown.refit_on_all_rows && ' After evaluation the chosen model is refit on all samples.'}
              </p>
            )}
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {shown.limitations?.map((l) => <li key={l}>{l}</li>)}
            </ul>
          </Card>
        </div>
      )}
    </section>
  )
}
