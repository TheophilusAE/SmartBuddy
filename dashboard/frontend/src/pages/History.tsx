import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { api, errorMessage, qs } from '../api'
import { useAuth } from '../auth'
import { useLive } from '../live'
import { fromLocalInput, localTime, num, toLocalInput } from '../format'
import MetricChart from '../components/MetricChart'
import { Badge, Button, Card, cx, EmptyState, ErrorNote, PageHeader, Skeleton } from '../components/ui'
import { rainView, windowView } from '../components/RainWindow'
import type { Reading, SeriesPoint } from '../types'

const PRESETS = [
  { id: '1h', label: '1 h', ms: 3600e3 },
  { id: '6h', label: '6 h', ms: 6 * 3600e3 },
  { id: '24h', label: '24 h', ms: 24 * 3600e3 },
  { id: '7d', label: '7 days', ms: 7 * 24 * 3600e3 },
] as const
const MAX_RANGE_MS = 31 * 24 * 3600e3
const PAGE_SIZE = 25

type PresetId = (typeof PRESETS)[number]['id'] | 'custom'

interface Range {
  start: Date
  end: Date
}

export default function HistoryPage() {
  const { user } = useAuth()
  const { stats } = useLive()
  const [preset, setPreset] = useState<PresetId>('24h')
  const [range, setRange] = useState<Range>(() => ({ start: new Date(Date.now() - 24 * 3600e3), end: new Date() }))
  const [customStart, setCustomStart] = useState(() => toLocalInput(new Date(Date.now() - 24 * 3600e3)))
  const [customEnd, setCustomEnd] = useState(() => toLocalInput(new Date()))
  const [includeSim, setIncludeSim] = useState(false)
  const [page, setPage] = useState(1)

  const [series, setSeries] = useState<SeriesPoint[] | null>(null)
  const [rows, setRows] = useState<Reading[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const params = useMemo(
    () => ({ start: range.start.toISOString(), end: range.end.toISOString(), include_simulated: includeSim }),
    [range, includeSim],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, list] = await Promise.all([
        api<{ points: SeriesPoint[] }>(`/readings/series${qs(params)}`),
        api<{ items: Reading[]; total: number }>(`/readings${qs({ ...params, page, page_size: PAGE_SIZE })}`),
      ])
      setSeries(s.points)
      setRows(list.items)
      setTotal(list.total)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [params, page])

  useEffect(() => {
    void load()
  }, [load])

  const choosePreset = (id: PresetId) => {
    setPreset(id)
    setPage(1)
    const p = PRESETS.find((x) => x.id === id)
    if (p) {
      const end = new Date()
      setRange({ start: new Date(end.getTime() - p.ms), end })
    }
  }

  const applyCustom = () => {
    const s = fromLocalInput(customStart)
    const e = fromLocalInput(customEnd)
    if (!s || !e) return setError('Pick a valid start and end time.')
    if (s >= e) return setError('Start must be before end.')
    if (e.getTime() - s.getTime() > MAX_RANGE_MS) return setError('The range is limited to 31 days.')
    setPage(1)
    setRange({ start: s, end: e })
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const startMs = range.start.getTime()
  const endMs = range.end.getTime()
  const exportHref = `/api/v1/readings/export.csv${qs(params)}`
  const lastReal = stats?.last_real_at ? new Date(stats.last_real_at).getTime() : null
  const stale = lastReal !== null && Date.now() - lastReal > 60e3 && endMs > Date.now() - 60e3

  return (
    <>
      <PageHeader
        title="History"
        subtitle={`View your sensor data history · ${localTime(range.start.toISOString())} – ${localTime(range.end.toISOString())}`}
        action={
          <div className="flex gap-2">
            <Button onClick={() => void load()} busy={loading} aria-label="Reload">
              <RefreshCw className="h-4 w-4" aria-hidden />
              Reload
            </Button>
            {user?.role === 'admin' && (
              <a
                href={exportHref}
                download
                className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-accent-ink shadow-sm hover:bg-accent/90"
              >
                <Download className="h-4 w-4" aria-hidden />
                Export CSV
              </a>
            )}
          </div>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface p-4 shadow-card">
        <div role="group" aria-label="Time range" className="inline-flex flex-wrap rounded-full bg-raised p-1">
          {[...PRESETS, { id: 'custom' as const, label: 'Custom' }].map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => (p.id === 'custom' ? setPreset('custom') : choosePreset(p.id))}
              aria-pressed={preset === p.id}
              className={cx(
                'rounded-full px-3.5 py-1.5 text-sm transition-colors',
                preset === p.id ? 'bg-accent font-medium text-accent-ink shadow-sm' : 'text-ink-2 hover:text-ink',
              )}
            >
              {p.label}
            </button>
          ))}
        </div>

        {preset === 'custom' && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-muted">
              From
              <input type="datetime-local" value={customStart} onChange={(e) => setCustomStart(e.target.value)} className="mt-1 block rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-ink" />
            </label>
            <label className="text-xs text-muted">
              To
              <input type="datetime-local" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} className="mt-1 block rounded-xl border border-line bg-surface px-3 py-1.5 text-sm text-ink" />
            </label>
            <Button variant="primary" onClick={applyCustom}>Apply</Button>
          </div>
        )}

        <label className="ml-auto flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--c-accent))]" checked={includeSim} onChange={(e) => { setIncludeSim(e.target.checked); setPage(1) }} />
          Include simulated data
        </label>
        <p className="w-full text-xs text-muted">Charts average readings into time buckets. Up to 31 days per query.</p>
      </div>

      {error && <div className="mb-4"><ErrorNote>{error}</ErrorNote></div>}
      {stale && <p className="mb-4"><Badge tone="warn">No new real readings for more than a minute</Badge></p>}
      {!loading && total === 0 && !includeSim && (stats?.simulated_readings ?? 0) > 0 && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-accent/30 bg-accent/10 px-4 py-3 text-sm">
          <span className="text-ink-2">
            No real readings in this range, but there is simulated test data. It's hidden by default so it can't be
            mistaken for real measurements.
          </span>
          <Button onClick={() => { setIncludeSim(true); setPage(1) }}>Show simulated data</Button>
        </div>
      )}

      {series === null ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[290px]" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <MetricChart points={series} metric="temperature_c" title="Temperature" unit="°C" digits={1} startMs={startMs} endMs={endMs} />
          <MetricChart points={series} metric="humidity_pct" title="Humidity" unit="%" digits={1} startMs={startMs} endMs={endMs} />
          <MetricChart points={series} metric="light_pct" title="Light" unit="%" digits={0} startMs={startMs} endMs={endMs} />
          <MetricChart points={series} metric="gas_adc_max" title="Gas, MQ-2 peak" unit="ADC" digits={0} startMs={startMs} endMs={endMs} />
        </div>
      )}

      <Card className="mt-6" title="Readings" subtitle={`${total.toLocaleString()} in this range`}>
        {rows.length === 0 && !loading ? (
          <EmptyState title="No readings in this range">Try a longer range, or check that the device is sending data.</EmptyState>
        ) : (
          <>
            <div className="-mx-5 overflow-x-auto sm:-mx-6">
              <table className="w-full min-w-[920px] text-left text-sm">
                <thead>
                  <tr className="border-y border-line bg-raised/60 text-xs uppercase tracking-wide text-muted">
                    <th className="px-5 py-3 font-semibold sm:px-6">Measured</th>
                    <th className="px-3 py-3 font-semibold">Device</th>
                    <th className="px-3 py-3 text-right font-semibold">Temp °C</th>
                    <th className="px-3 py-3 text-right font-semibold">Humidity %</th>
                    <th className="px-3 py-3 text-right font-semibold">Light %</th>
                    <th className="px-3 py-3 font-semibold">Motion</th>
                    <th className="px-3 py-3 text-right font-semibold">Gas ADC</th>
                    <th className="px-3 py-3 font-semibold">Rain</th>
                    <th className="px-3 py-3 font-semibold">Window</th>
                    <th className="px-5 py-3 font-semibold sm:px-6">Flags</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b border-line/70 transition-colors last:border-0 hover:bg-raised/50">
                      <td className="whitespace-nowrap px-5 py-3 sm:px-6">{localTime(r.measured_at)}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-ink-2">{r.device_id}</td>
                      <td className="px-3 py-3 text-right font-medium">{num(r.temperature_c)}</td>
                      <td className="px-3 py-3 text-right font-medium">{num(r.humidity_pct)}</td>
                      <td className="px-3 py-3 text-right font-medium">{num(r.light_pct, 0)}</td>
                      <td className="px-3 py-3">{r.motion_detected === null ? '—' : r.motion_detected ? 'Yes' : 'No'}</td>
                      <td className="px-3 py-3 text-right font-medium">{r.gas_adc ?? '—'}</td>
                      <td className="whitespace-nowrap px-3 py-3">{r.rain_status === null ? '—' : rainView(r.rain_status).label}</td>
                      <td className="whitespace-nowrap px-3 py-3">
                        {r.window_state === null ? '—' : `${windowView(r.window_state).label}${r.servo_angle !== null ? ` · ${r.servo_angle}°` : ''}`}
                      </td>
                      <td className="px-5 py-3 sm:px-6">
                        <span className="flex flex-wrap gap-1">
                          {r.is_simulated && <Badge tone="accent">simulated</Badge>}
                          {!r.valid && <Badge tone="warn">incomplete</Badge>}
                          {!r.timestamp_trusted && <Badge>rx time</Badge>}
                          {r.out_of_order && <Badge>out of order</Badge>}
                          {r.gas_warning_local && <Badge tone="danger">gas alarm</Badge>}
                          {r.valid && !r.is_simulated && !r.gas_warning_local && r.timestamp_trusted && !r.out_of_order && (
                            <Badge tone="good">ok</Badge>
                          )}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-muted">Page {page} of {pages}</span>
              <div className="flex gap-2">
                <Button disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button disabled={page >= pages || loading} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  )
}
