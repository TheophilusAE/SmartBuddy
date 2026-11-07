import { useEffect, useState, type ReactNode } from 'react'
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Droplets, Fan, Flame, Lightbulb, Minus, Sun, Thermometer, Volume2 } from 'lucide-react'
import { api } from '../api'
import { useLive, usePrimaryDevice } from '../live'
import { ageSeconds, num, relative } from '../format'
import { RANGES, rangeMs, trend, useSeries, type RangeId } from '../hooks'
import MetricChart, { METRIC_COLOR, type MetricKey } from '../components/MetricChart'
import Sparkline from '../components/Sparkline'
import RainWindowCard from '../components/RainWindow'
import { freshnessOf } from '../components/status'
import { Card, cx, EmptyState, IconBubble, Segmented, Skeleton, StatusDot, type Hue } from '../components/ui'
import type { Advice, Reading, SensorState } from '../types'

const TEMP_OK = [20, 26] as const
const HUMIDITY_OK = [30, 60] as const
const DIM_LIGHT_PCT = 30

type Tone = 'good' | 'warn' | 'danger' | 'neutral'

const CHIP: Record<Tone, string> = {
  good: 'bg-good/15 text-good-ink',
  warn: 'bg-warn/15 text-warn-ink',
  danger: 'bg-danger/15 text-danger-ink',
  neutral: 'bg-raised text-ink-2',
}

interface Status {
  word: string
  tone: Tone
}

function sensorProblem(state: SensorState): Status | null {
  if (state === 'warming_up') return { word: 'Warming up', tone: 'neutral' }
  if (state === 'error') return { word: 'Sensor error', tone: 'danger' }
  return null
}

function tempStatus(r: Reading): Status {
  const t = r.temperature_c
  if (t === null) return sensorProblem(r.sensor_status.dht) ?? { word: 'No reading', tone: 'neutral' }
  if (t > TEMP_OK[1]) return { word: 'Warm', tone: 'warn' }
  if (t < TEMP_OK[0]) return { word: 'Cool', tone: 'warn' }
  return { word: 'Normal', tone: 'good' }
}

function humStatus(r: Reading): Status {
  const h = r.humidity_pct
  if (h === null) return sensorProblem(r.sensor_status.dht) ?? { word: 'No reading', tone: 'neutral' }
  if (h > HUMIDITY_OK[1]) return { word: 'Humid', tone: 'warn' }
  if (h < HUMIDITY_OK[0]) return { word: 'Dry', tone: 'warn' }
  return { word: 'Normal', tone: 'good' }
}

function lightStatus(r: Reading): Status {
  if (r.light_pct === null) return sensorProblem(r.sensor_status.ldr) ?? { word: 'No reading', tone: 'neutral' }
  return r.light_pct < DIM_LIGHT_PCT ? { word: 'Dim', tone: 'neutral' } : { word: 'Bright', tone: 'good' }
}

function motionStatus(r: Reading): Status {
  if (r.motion_detected === null) return sensorProblem(r.sensor_status.pir) ?? { word: 'No reading', tone: 'neutral' }
  return r.motion_detected ? { word: 'Movement', tone: 'neutral' } : { word: 'Still', tone: 'neutral' }
}

function gasStatus(r: Reading, alarm: boolean): Status {
  if (alarm) return { word: 'Alarm', tone: 'danger' }
  if (r.gas_adc === null) return sensorProblem(r.sensor_status.mq2) ?? { word: 'No reading', tone: 'neutral' }
  return { word: 'No alarm', tone: 'good' }
}

function greeting(hour: number): string {
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function TrendChip({ delta, digits, unit }: { delta: number | null; digits: number; unit: string }) {
  if (delta === null) return null
  const flat = Math.abs(delta) < Math.pow(10, -digits) / 2
  const Icon = flat ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className="inline-flex items-center gap-0.5 text-xs text-muted tabular" title="Change over the last hour">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {flat ? 'steady' : `${delta > 0 ? '+' : ''}${delta.toFixed(digits)}${unit}`}
      <span className="sr-only"> in the last hour</span>
    </span>
  )
}

function SensorCard({
  label,
  hue,
  icon,
  value,
  unit,
  status,
  faded,
  alarm = false,
  trendValues,
  metric,
  digits = 0,
  footnote,
}: {
  label: string
  hue: Hue
  icon: ReactNode
  value: string
  unit?: string
  status: Status
  faded: boolean
  alarm?: boolean
  trendValues?: (number | null)[]
  metric?: MetricKey
  digits?: number
  footnote?: ReactNode
}) {
  return (
    <div
      className={cx(
        'flex flex-col rounded-card border bg-surface p-4 shadow-card transition-transform hover:-translate-y-0.5',
        alarm ? 'border-danger/50 ring-1 ring-danger/30' : 'border-line',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <IconBubble hue={alarm ? 'danger' : hue}>{icon}</IconBubble>
        {trendValues && <TrendChip delta={trend(trendValues)} digits={digits} unit={unit === '°C' ? '°' : unit === '%' ? '%' : ''} />}
      </div>
      <div className={cx('mt-4 flex items-baseline gap-1', faded && 'opacity-50')}>
        <span className="text-[32px] font-bold leading-none tracking-tight tabular">{value}</span>
        {unit && <span className="text-base font-medium text-ink-2">{unit}</span>}
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted">{label}</span>
        <span className={cx('rounded-full px-2 py-0.5 text-xs font-semibold', CHIP[status.tone])}>{status.word}</span>
      </div>
      {footnote && <p className="mt-2 text-xs text-muted">{footnote}</p>}
      {trendValues && metric && (
        <div className="mt-auto pt-3">
          <Sparkline values={trendValues} color={METRIC_COLOR[metric]} label={`${label} over the last hour`} />
        </div>
      )}
    </div>
  )
}

function OutputRow({ label, icon, on }: { label: string; icon: ReactNode; on: boolean | null }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-raised/50 px-3.5 py-3">
      <IconBubble hue={on ? 'accent' : 'neutral'} size="sm">
        {icon}
      </IconBubble>
      <span className="flex-1 font-medium">{label}</span>
      <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', on ? 'bg-good/15 text-good-ink' : 'bg-raised text-muted')}>
        {on === null ? 'Unknown' : on ? 'On' : 'Off'}
      </span>
    </div>
  )
}

const CHART_TABS: { id: MetricKey; label: string; unit: string; digits: number }[] = [
  { id: 'temperature_c', label: 'Temperature', unit: '°C', digits: 1 },
  { id: 'humidity_pct', label: 'Humidity', unit: '%', digits: 0 },
  { id: 'light_pct', label: 'Light', unit: '%', digits: 0 },
  { id: 'gas_adc_max', label: 'Gas', unit: 'ADC', digits: 0 },
]

export default function Overview() {
  const { reading, stats, warnings, now, link } = useLive()
  const device = usePrimaryDevice()
  const [estimate, setEstimate] = useState<number | null>(null)
  const [range, setRange] = useState<RangeId>('6h')
  const [metric, setMetric] = useState<MetricKey>('temperature_c')

  const includeSim = reading?.is_simulated ?? false
  const hour = useSeries(3600e3, includeSim, reading?.device_id)
  const overview = useSeries(rangeMs(range), includeSim, reading?.device_id)

  useEffect(() => {
    api<Advice>('/ml/advice')
      .then((a) => setEstimate(a.basis === 'model' && typeof a.estimate === 'number' ? a.estimate : null))
      .catch(() => setEstimate(null))
  }, [reading?.id])

  const clock = new Date(now)
  const dateText = clock.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  if (link === 'connecting' && !reading && !stats) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-44" />)}
        </div>
        <Skeleton className="h-80" />
      </div>
    )
  }

  const fresh = freshnessOf(reading, device, now)
  const faded = fresh !== 'live'
  const alarm = !!reading && warnings.some((w) => w.device_id === reading.device_id)
  const target = stats?.target_valid_readings ?? 1000
  const valid = stats?.real_valid_readings ?? 0
  const pct = Math.min(100, (valid / target) * 100)
  const tab = CHART_TABS.find((t) => t.id === metric) ?? CHART_TABS[0]!

  const issues = reading
    ? [tempStatus(reading), humStatus(reading)].filter((s) => s.tone === 'warn').map((s) => s.word.toLowerCase())
    : []
  let subtitle = 'Your smart home is running smoothly.'
  if (!reading) subtitle = 'Waiting for the first reading from your ESP32.'
  else if (alarm) subtitle = 'The gas sensor has raised an alarm - please check the room.'
  else if (fresh === 'offline') subtitle = 'Your ESP32 is offline. Showing the last readings received.'
  else if (fresh === 'stale') subtitle = 'Readings are delayed. Showing the last values received.'
  else if (reading.rain_status === 'error') subtitle = 'The rain sensor has an error - the window keeps its position.'
  else if (reading.rain_status === 'rain') subtitle = "Rain detected - the ESP32 closes the window by itself."
  else if (issues.length) subtitle = `The room is ${issues.join(' and ')} - see Comfort for suggestions.`

  const motionShare = hour.points.filter((p) => p.motion_any !== null)
  const motionPct = motionShare.length ? Math.round((motionShare.filter((p) => p.motion_any).length / motionShare.length) * 100) : null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight">{greeting(clock.getHours())}!</h1>
          <p className="mt-1 text-ink-2">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-2 shadow-sm">
          <StatusDot tone={device?.online ? 'good' : 'danger'} pulse={!!device?.online}>
            <span className="font-medium text-ink tabular">{dateText}</span>
          </StatusDot>
        </div>
      </div>

      {reading?.is_simulated && (
        <p className="rounded-2xl border border-accent/30 bg-accent/10 px-4 py-2.5 text-sm text-ink-2">
          Showing <span className="font-semibold text-accent">simulated test data</span> - it isn't counted as real readings.
        </p>
      )}

      {alarm && reading && (
        <section role="alert" className="flex items-start gap-4 rounded-card border border-danger/30 bg-danger/10 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-danger text-white">
            <AlertTriangle className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h2 className="text-lg font-semibold text-danger-ink">Gas / smoke alarm</h2>
            <p className="mt-0.5 text-ink">
              The gas sensor has raised an alarm{reading.gas_adc !== null ? ` (current MQ-2 reading ${reading.gas_adc})` : ''}. Check the room
              and let fresh air in if it's safe.
            </p>
            <p className="mt-1 text-sm text-muted">Hobby sensor, not a certified gas detector · updated {relative(ageSeconds(reading.received_at, now))}</p>
          </div>
        </section>
      )}

      {!reading ? (
        <Card>
          <EmptyState icon={<Activity className="h-6 w-6" aria-hidden />} title="No sensor data yet">
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-left">
              <li>Power the ESP32. It joins the Wi-Fi from <code>secrets.h</code> and sends a reading every 2 s.</li>
              <li>Start the backend with <code>HOST=0.0.0.0</code> so the ESP32 can reach it.</li>
              <li>No Wi-Fi? Plug it in over USB and run <code>scripts/serial_bridge.py --port COMx</code>.</li>
            </ol>
          </EmptyState>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <SensorCard
              label="Temperature"
              hue="temp"
              icon={<Thermometer className="h-5 w-5" aria-hidden />}
              value={num(reading.temperature_c)}
              unit="°C"
              status={tempStatus(reading)}
              faded={faded}
              trendValues={hour.points.map((p) => p.temperature_c)}
              metric="temperature_c"
              digits={1}
            />
            <SensorCard
              label="Humidity"
              hue="hum"
              icon={<Droplets className="h-5 w-5" aria-hidden />}
              value={num(reading.humidity_pct, 0)}
              unit="%"
              status={humStatus(reading)}
              faded={faded}
              trendValues={hour.points.map((p) => p.humidity_pct)}
              metric="humidity_pct"
            />
            <SensorCard
              label="Light"
              hue="lux"
              icon={<Sun className="h-5 w-5" aria-hidden />}
              value={num(reading.light_pct, 0)}
              unit="%"
              status={lightStatus(reading)}
              faded={faded}
              trendValues={hour.points.map((p) => p.light_pct)}
              metric="light_pct"
            />
            <SensorCard
              label="Motion"
              hue="motion"
              icon={<Activity className="h-5 w-5" aria-hidden />}
              value={reading.motion_detected === null ? '—' : reading.motion_detected ? 'Yes' : 'No'}
              status={motionStatus(reading)}
              faded={faded}
              footnote={motionPct === null ? undefined : `Movement in ${motionPct}% of the last hour`}
            />
            <SensorCard
              label="Gas / smoke"
              hue="gas"
              icon={<Flame className="h-5 w-5" aria-hidden />}
              value={reading.gas_adc === null ? '—' : String(reading.gas_adc)}
              unit="ADC"
              status={gasStatus(reading, alarm)}
              faded={faded}
              alarm={alarm}
              trendValues={hour.points.map((p) => p.gas_adc_max)}
              metric="gas_adc_max"
            />
          </div>

          <RainWindowCard reading={reading} device={device} now={now} />

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Card
              className="xl:col-span-2"
              title="Sensor overview"
              subtitle={`${tab.label} (${tab.unit})`}
              action={<Segmented label="Time range" options={RANGES} value={range} onChange={setRange} />}
            >
              <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Metric">
                {CHART_TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setMetric(t.id)}
                    aria-pressed={metric === t.id}
                    className={cx(
                      'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
                      metric === t.id ? 'border-transparent bg-raised font-semibold text-ink' : 'border-line text-ink-2 hover:bg-raised',
                    )}
                  >
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: METRIC_COLOR[t.id] }} aria-hidden />
                    {t.label}
                  </button>
                ))}
              </div>
              {overview.loading && !overview.points.length ? (
                <Skeleton className="h-[260px]" />
              ) : (
                <MetricChart
                  bare
                  points={overview.points}
                  metric={metric}
                  title={tab.label}
                  unit={tab.unit}
                  digits={tab.digits}
                  startMs={overview.startMs}
                  endMs={overview.endMs}
                  height={260}
                />
              )}
            </Card>

            <div className="space-y-6">
              <Card title="Outputs" subtitle="Switched automatically by the ESP32">
                <div className="space-y-2.5">
                  <OutputRow label="Fan" icon={<Fan className="h-4 w-4" aria-hidden />} on={device?.actuators.fan ?? null} />
                  <OutputRow label="LED" icon={<Lightbulb className="h-4 w-4" aria-hidden />} on={device?.actuators.light ?? null} />
                  <OutputRow label="Buzzer" icon={<Volume2 className="h-4 w-4" aria-hidden />} on={device?.actuators.buzzer ?? null} />
                </div>
                <p className="mt-3 text-xs text-muted">Monitor-only: the firmware's rules switch these. See Devices for the rules.</p>
              </Card>

              <Card title="Data collection" subtitle="Valid real readings">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[32px] font-bold leading-none tabular">{valid.toLocaleString()}</span>
                  <span className="text-ink-2">/ {target.toLocaleString()}</span>
                  <span className="ml-auto text-sm font-semibold text-accent tabular">{pct.toFixed(0)}%</span>
                </div>
                <div
                  className="mt-3 h-2.5 overflow-hidden rounded-full bg-raised"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={target}
                  aria-valuenow={valid}
                  aria-label="Valid real readings collected"
                >
                  <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${pct}%` }} />
                </div>
                {estimate !== null && (
                  <p className="mt-3 text-sm text-ink-2">
                    Comfort estimate <span className="font-semibold text-ink tabular">{estimate.toFixed(1)} / 5</span>
                  </p>
                )}
              </Card>
            </div>
          </div>

          <p className="text-xs text-muted">
            Light is a relative level (0–100 %, not lux). Gas is a raw MQ-2 sensor count (not ppm). Motion means the PIR sensed movement, not
            who or how many.
          </p>
        </>
      )}
    </div>
  )
}
