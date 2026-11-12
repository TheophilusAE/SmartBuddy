import { useCallback, useEffect, useState } from 'react'
import { BrainCircuit, CheckCircle2, CircleDashed, Copy, Database, Droplets, FlaskConical, History, Play, Sun, Thermometer, XCircle } from 'lucide-react'
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, type TooltipProps } from 'recharts'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useLive } from '../live'
import { localTime, num } from '../format'
import { Badge, Button, Card, cx, ErrorNote, IconBubble, PageHeader, ProgressRing, Skeleton, Stat } from '../components/ui'
import ForecastEvaluation from '../components/ForecastEvaluation'
import type { Advice, ForecastResult, MlStatus, TrainingResult } from '../types'

interface EvaluationResponse {
  deployed: TrainingResult | null
  last_attempt: TrainingResult | null
  forecast: { deployed: ForecastResult | null; last_attempt: ForecastResult | null }
}


const MODEL_NAMES: Record<string, string> = {
  baseline_mean: 'Baseline (predicts the average)',
  decision_tree: 'Decision tree',
  random_forest: 'Random forest',
}

const SCALE = ['Very uncomfortable', 'Uncomfortable', 'Neutral', 'Comfortable', 'Very comfortable']

const TRAIN_COMMANDS = 'python -m ml.prepare_dataset\npython -m ml.train_model --plot --publish'

function MetricsTable({ result }: { result: TrainingResult }) {
  const metrics = result.metrics ?? {}
  const baseline = metrics.baseline_mean
  const maxMae = Math.max(...Object.values(metrics).map((m) => m.mae), 0.001)
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-6">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr className="border-y border-line bg-raised/60 text-xs uppercase tracking-wide text-muted">
            <th className="px-5 py-3 font-semibold sm:px-6">Model</th>
            <th className="px-3 py-3 text-right font-semibold">MAE</th>
            <th className="px-3 py-3 font-semibold" aria-hidden />
            <th className="px-3 py-3 text-right font-semibold">RMSE</th>
            <th className="px-5 py-3 text-right font-semibold sm:px-6">vs baseline</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {Object.entries(metrics).map(([name, m]) => {
            const delta = baseline && name !== 'baseline_mean' ? ((m.mae - baseline.mae) / baseline.mae) * 100 : null
            return (
              <tr key={name} className="border-b border-line/70 last:border-0">
                <td className="px-5 py-3 sm:px-6">
                  <span className="font-medium">{MODEL_NAMES[name] ?? name}</span>
                  {result.best_candidate === name && <span className="ml-2"><Badge tone="accent">best</Badge></span>}
                </td>
                <td className="px-3 py-3 text-right font-semibold">{m.mae.toFixed(3)}</td>
                <td className="w-32 px-3 py-3">
                  <div className="h-2 rounded-full bg-raised">
                    <div className={cx('h-2 rounded-full', name === 'baseline_mean' ? 'bg-muted' : 'bg-accent')} style={{ width: `${(m.mae / maxMae) * 100}%` }} />
                  </div>
                </td>
                <td className="px-3 py-3 text-right">{m.rmse.toFixed(3)}</td>
                <td className={cx('px-5 py-3 text-right font-medium sm:px-6', delta !== null && delta < 0 ? 'text-good-ink' : delta !== null ? 'text-danger-ink' : 'text-muted')}>
                  {delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}%`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-3 px-5 text-xs text-muted sm:px-6">Lower is better. Errors are in rating points (scale 1–5), measured on held-out sessions.</p>
    </div>
  )
}

function ActualVsPredicted({ points }: { points: { actual: number; predicted: number }[] }) {
  const tooltip = ({ active, payload }: TooltipProps<number, string>) => {
    const p = payload?.[0]?.payload as { actual: number; predicted: number } | undefined
    if (!active || !p) return null
    return (
      <div className="rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-card tabular">
        <div>Actual rating: <strong>{p.actual}</strong></div>
        <div>Predicted: <strong>{p.predicted.toFixed(2)}</strong></div>
      </div>
    )
  }
  return (
    <figure>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 12, bottom: 16, left: -8 }}>
            <CartesianGrid stroke="var(--chart-grid)" />
            <XAxis type="number" dataKey="actual" name="Actual" domain={[0.5, 5.5]} ticks={[1, 2, 3, 4, 5]}
              tick={{ fill: 'var(--chart-label)', fontSize: 11 }} stroke="var(--chart-axis)"
              label={{ value: 'Actual rating', position: 'insideBottom', offset: -8, fill: 'var(--chart-label)', fontSize: 11 }} />
            <YAxis type="number" dataKey="predicted" name="Predicted" domain={[0.5, 5.5]} ticks={[1, 2, 3, 4, 5]}
              tick={{ fill: 'var(--chart-label)', fontSize: 11 }} stroke="var(--chart-axis)" width={44} />
            <ReferenceLine segment={[{ x: 0.5, y: 0.5 }, { x: 5.5, y: 5.5 }]} stroke="var(--chart-axis)" strokeDasharray="4 4" ifOverflow="hidden" />
            <Tooltip content={tooltip} cursor={false} isAnimationActive={false} />
            <Scatter data={points} fill="rgb(var(--c-accent))" fillOpacity={0.75} isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-xs text-muted">
        Each dot is one held-out rating; dots on the dashed line would be perfect predictions. Ratings are whole numbers,
        so dots stack in columns.
      </figcaption>
    </figure>
  )
}

function statusLabel(s: string | undefined): { text: string; tone: 'good' | 'warn' | 'neutral' } {
  if (s === 'deployed') return { text: 'Deployed', tone: 'good' }
  if (s === 'no_improvement') return { text: 'Did not beat baseline', tone: 'warn' }
  if (s === 'insufficient_data') return { text: 'Not enough data', tone: 'warn' }
  return { text: 'Never run', tone: 'neutral' }
}

export default function Evaluation() {
  const { reading } = useLive()
  const [status, setStatus] = useState<MlStatus | null>(null)
  const [deployed, setDeployed] = useState<TrainingResult | null>(null)
  const [last, setLast] = useState<TrainingResult | null>(null)
  const [forecast, setForecast] = useState<EvaluationResponse['forecast'] | null>(null)
  const [advice, setAdvice] = useState<Advice | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const [training, setTraining] = useState(false)
  const [trainNote, setTrainNote] = useState<string | null>(null)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([
        api<MlStatus>('/ml/status'),
        api<EvaluationResponse>('/ml/evaluation'),
      ])
      setStatus(s)
      setDeployed(e.deployed)
      setLast(e.last_attempt)
      setForecast(e.forecast)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    api<Advice>('/ml/advice').then(setAdvice).catch(() => setAdvice(null))
  }, [reading?.id])

  const trainNow = async () => {
    setTraining(true)
    setTrainNote(null)
    setError(null)
    try {
      const res = await api<TrainingResult>('/ml/train', { method: 'POST' })
      setTrainNote(res.status === 'deployed' ? `Deployed ${res.model_version} (${MODEL_NAMES[res.algorithm ?? ''] ?? res.algorithm}).` : res.message ?? statusLabel(res.status).text)
      await load()
      api<Advice>('/ml/advice').then(setAdvice).catch(() => setAdvice(null))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setTraining(false)
    }
  }

  const copyCommands = async () => {
    try {
      await navigator.clipboard.writeText(TRAIN_COMMANDS)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard blocked
    }
  }

  const shown = deployed ?? (last && last.metrics ? last : null)
  const usable = status?.usable_feedback ?? 0
  const needed = status?.min_labels ?? 30
  const lastState = statusLabel(last?.status)

  const best = shown?.best_candidate ? shown.metrics?.[shown.best_candidate] : undefined
  const base = shown?.metrics?.baseline_mean
  const improvement = best && base && base.mae > 0 ? (base.mae - best.mae) / base.mae : null

  const logs = [last, deployed && deployed.attempted_at !== last?.attempted_at ? deployed : null].filter(
    (x): x is TrainingResult => !!x,
  )
  const hasModel = advice?.basis === 'model' && typeof advice.estimate === 'number'

  return (
    <>
      <PageHeader
        title="ML evaluation"
        subtitle="How well the comfort model predicts your own ratings, compared with a simple baseline."
        action={
          last ? <span className="text-sm text-muted">Last trained: {localTime(last.attempted_at)}</span> : undefined
        }
      />
      {error && <div className="mb-4"><ErrorNote>{error}</ErrorNote></div>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {loading
          ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />)
          : [
              { label: 'Deployed model', value: status?.model_version ?? 'None', hint: status?.algorithm ? MODEL_NAMES[status.algorithm] : 'nothing deployed yet', icon: <BrainCircuit className="h-5 w-5" aria-hidden />, hue: 'accent' as const },
              { label: 'Usable ratings', value: `${usable} / ${needed}`, hint: `${status?.usable_sessions ?? 0} of ${status?.min_sessions ?? 2} separate days`, icon: <Database className="h-5 w-5" aria-hidden />, hue: 'hum' as const },
              { label: 'Last training', value: lastState.text, hint: last ? localTime(last.attempted_at) : 'run the training script', icon: <History className="h-5 w-5" aria-hidden />, hue: 'motion' as const },
              { label: 'Evaluation samples', value: shown?.split?.test_rows ?? '—', hint: shown?.split ? `${shown.split.test_sessions} held-out session(s)` : 'after training', icon: <FlaskConical className="h-5 w-5" aria-hidden />, hue: 'gas' as const },
            ].map((s) => (
              <div key={s.label} className="rounded-card border border-line bg-surface p-5 shadow-card">
                <Stat label={s.label} value={s.value} hint={s.hint} icon={<IconBubble hue={s.hue}>{s.icon}</IconBubble>} />
              </div>
            ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Model performance" subtitle={shown ? (deployed ? 'Deployed model' : 'Latest attempt (not deployed)') : 'Waiting for enough ratings'}>
          <div className="flex flex-col items-center text-center">
            {loading ? (
              <Skeleton className="h-[148px] w-[148px] rounded-full" />
            ) : shown && improvement !== null ? (
              <ProgressRing value={Math.max(0, improvement)} size={148} colorClass={improvement > 0 ? 'text-good' : 'text-danger'}>
                <span className="text-3xl font-bold tabular">{Math.round(improvement * 100)}%</span>
                <span className="text-xs text-muted">{improvement > 0 ? 'better' : 'not better'}</span>
              </ProgressRing>
            ) : (
              <ProgressRing value={usable / needed} size={148}>
                <span className="text-3xl font-bold tabular">{usable}</span>
                <span className="text-xs text-muted">of {needed} ratings</span>
              </ProgressRing>
            )}
            <p className="mt-4 font-semibold">{shown && improvement !== null ? 'Error vs. the baseline' : 'Not enough labelled data'}</p>
            <p className="mt-1 max-w-[17rem] text-sm text-muted">
              {shown && improvement !== null
                ? 'How much lower the best model\'s average error (MAE) is than always guessing the average rating.'
                : `Collect at least ${needed} ratings (Overview or Comfort page), then press Train now. No metrics are shown until then.`}
            </p>
          </div>
          {shown && best && base && (
            <dl className="mt-5 grid grid-cols-3 gap-2 text-center">
              {[
                { k: 'MAE', v: best.mae.toFixed(2) },
                { k: 'RMSE', v: best.rmse.toFixed(2) },
                { k: 'Baseline MAE', v: base.mae.toFixed(2) },
              ].map((m) => (
                <div key={m.k} className="rounded-2xl bg-raised/60 px-2 py-3">
                  <dt className="text-xs text-muted">{m.k}</dt>
                  <dd className="mt-0.5 text-lg font-semibold tabular">{m.v}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>

        <Card title="Prediction example" subtitle="Current conditions">
          {reading ? (
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-raised px-3 py-1.5 text-sm font-medium tabular"><Thermometer className="h-4 w-4 text-temp" aria-hidden />{num(reading.temperature_c)} °C</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-raised px-3 py-1.5 text-sm font-medium tabular"><Droplets className="h-4 w-4 text-hum" aria-hidden />{num(reading.humidity_pct, 0)} %</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-raised px-3 py-1.5 text-sm font-medium tabular"><Sun className="h-4 w-4 text-lux" aria-hidden />{num(reading.light_pct, 0)} %</span>
            </div>
          ) : (
            <p className="text-sm text-muted">No live reading yet.</p>
          )}
          {hasModel ? (
            <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl border border-good/30 bg-good/10 px-4 py-4">
              <div>
                <div className="text-sm text-good-ink">Predicted</div>
                <div className="text-lg font-semibold text-good-ink">
                  {SCALE[Math.min(4, Math.max(0, Math.round(advice!.estimate as number) - 1))]} · {(advice!.estimate as number).toFixed(1)} / 5
                </div>
              </div>
              <CheckCircle2 className="h-6 w-6 text-good-ink" aria-hidden />
            </div>
          ) : (
            <div className="mt-5 flex items-center gap-3 rounded-2xl border border-dashed border-line px-4 py-4 text-sm text-muted">
              <CircleDashed className="h-5 w-5 shrink-0" aria-hidden />
              A prediction appears here once a model has been trained and deployed.
            </div>
          )}
        </Card>

        <Card title="Training log">
          {logs.length === 0 ? (
            <p className="text-sm text-muted">Training hasn't been run yet.</p>
          ) : (
            <ol className="space-y-3">
              {logs.map((l) => {
                const st = statusLabel(l.status)
                return (
                  <li key={l.attempted_at} className="flex items-start gap-3">
                    {st.tone === 'good' ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" aria-hidden />
                    ) : (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
                    )}
                    <div className="text-sm">
                      <div className="font-medium">{localTime(l.attempted_at)}</div>
                      <div className="text-muted">
                        {st.text}
                        {l.summary ? ` · ${l.summary.rows} rows, ${l.summary.sessions} session(s)` : ''}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ol>
          )}
          {isAdmin && (
            <div className="mt-5">
              <Button variant="primary" className="w-full" busy={training} onClick={() => void trainNow()}>
                <Play className="h-4 w-4" aria-hidden />
                Train now
              </Button>
              <p className="mt-2 text-xs text-muted">
                Uses every usable rating in the database. The model is saved there too, so the laptop and Render both use it.
              </p>
              {trainNote && <p className="mt-2 text-sm font-medium" role="status">{trainNote}</p>}
            </div>
          )}
          <div className="mt-5 rounded-2xl bg-raised/60 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">Or from the laptop (in dashboard/)</span>
              <button type="button" onClick={() => void copyCommands()} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-ink-2 hover:bg-surface" aria-label="Copy training commands">
                <Copy className="h-3.5 w-3.5" aria-hidden />
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <pre className="whitespace-pre-wrap break-all text-xs leading-relaxed text-ink">{TRAIN_COMMANDS}</pre>
          </div>
        </Card>
      </div>

      {shown && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card title="Model comparison" subtitle={shown.beats_baseline === false ? 'Latest attempt did not beat the baseline, so nothing was deployed' : undefined}>
              <MetricsTable result={shown} />
            </Card>
            <Card title="Actual vs predicted" subtitle="Held-out sessions">
              {shown.test_predictions?.length ? <ActualVsPredicted points={shown.test_predictions} /> : <p className="text-sm text-muted">No predictions stored.</p>}
            </Card>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card title="Training data">
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-muted">Labelled rows</dt>
                <dd className="text-right font-medium tabular">{shown.summary.rows}</dd>
                <dt className="text-muted">Sessions (user × day)</dt>
                <dd className="text-right font-medium tabular">{shown.summary.sessions}</dd>
                <dt className="text-muted">Features</dt>
                <dd className="text-right font-medium">{shown.features.join(', ')}</dd>
                <dt className="text-muted">Rating counts</dt>
                <dd className="text-right font-medium tabular">{Object.entries(shown.summary.rating_counts).map(([k, v]) => `${k}: ${v}`).join(' · ')}</dd>
              </dl>
            </Card>
            <Card title="Method and limitations">
              {shown.split && (
                <p className="text-sm text-ink-2">
                  {shown.split.method}: {shown.split.train_rows} training rows from {shown.split.train_sessions} session(s), {shown.split.test_rows} test rows
                  from {shown.split.test_sessions} session(s), seed {shown.split.random_state}. Ratings from the same session never appear on both sides.
                  {shown.refit_on_all_rows && ' After evaluation the chosen model is refit on all rows.'}
                </p>
              )}
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-2">
                {shown.limitations?.map((l) => <li key={l}>{l}</li>)}
              </ul>
            </Card>
          </div>
        </>
      )}

      <ForecastEvaluation
        deployed={forecast?.deployed ?? null}
        last={forecast?.last_attempt ?? null}
        isAdmin={isAdmin}
        onTrained={() => void load()}
      />
    </>
  )
}
