import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from 'recharts'
import { shortTime } from '../format'
import type { SeriesPoint } from '../types'
import { cx } from './ui'

export type MetricKey = 'temperature_c' | 'humidity_pct' | 'light_pct' | 'gas_adc_max'

export const METRIC_COLOR: Record<MetricKey, string> = {
  temperature_c: 'var(--chart-temp)',
  humidity_pct: 'var(--chart-hum)',
  light_pct: 'var(--chart-lux)',
  gas_adc_max: 'var(--chart-gas)',
}

export default function MetricChart({
  points,
  metric,
  title,
  unit,
  digits,
  startMs,
  endMs,
  height = 220,
  bare = false,
}: {
  points: SeriesPoint[]
  metric: MetricKey
  title: string
  unit: string
  digits: number
  startMs: number
  endMs: number
  height?: number
  bare?: boolean
}) {
  const gradientId = useId()
  const color = METRIC_COLOR[metric]
  const withDate = endMs - startMs > 36 * 3600 * 1000
  const known = points.filter((p) => p[metric] !== null)
  const latest = known.length ? known[known.length - 1]![metric] : null

  const tooltip = ({ active, payload }: TooltipProps<number, string>) => {
    const p = payload?.[0]?.payload as SeriesPoint | undefined
    if (!active || !p) return null
    const v = p[metric]
    return (
      <div className="rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-card">
        <div className="text-muted">{shortTime(p.t, true)}</div>
        <div className="mt-0.5 text-sm font-semibold text-ink tabular">{v === null ? 'no data' : `${v.toFixed(digits)} ${unit}`}</div>
        <div className="text-muted">
          {p.samples} reading{p.samples === 1 ? '' : 's'} {metric === 'gas_adc_max' ? '(peak)' : 'averaged'}
        </div>
      </div>
    )
  }

  const chart = known.length ? (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 6, bottom: 0, left: -14 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[startMs, endMs]}
            tickFormatter={(v: number) => shortTime(v, withDate)}
            tick={{ fill: 'var(--chart-label)', fontSize: 11 }}
            stroke="var(--chart-axis)"
            tickLine={false}
            minTickGap={48}
          />
          <YAxis
            tick={{ fill: 'var(--chart-label)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={52}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : String(Number(v.toFixed(1))))}
          />
          <Tooltip content={tooltip} cursor={{ stroke: 'var(--chart-axis)', strokeWidth: 1 }} isAnimationActive={false} />
          <Area
            type="monotone"
            dataKey={metric}
            stroke={color}
            strokeWidth={2.5}
            fill={`url(#${gradientId})`}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: 'rgb(var(--c-surface))', fill: color }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  ) : (
    <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
      No valid readings in this range
    </div>
  )

  if (bare) return chart

  return (
    <figure className="rounded-card border border-line bg-surface p-5 shadow-card">
      <figcaption className="mb-3 flex items-center justify-between gap-2">
        <span className="font-semibold text-ink">
          {title} <span className="font-normal text-muted">({unit})</span>
        </span>
        {latest !== null && (
          <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold tabular')} style={{ color, backgroundColor: 'rgb(var(--c-raised))' }}>
            latest {latest.toFixed(digits)} {unit}
          </span>
        )}
      </figcaption>
      {chart}
    </figure>
  )
}
