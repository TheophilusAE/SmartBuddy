import { useId } from 'react'

export default function Sparkline({
  values,
  color,
  label,
  height = 44,
}: {
  values: (number | null)[]
  color: string
  label: string
  height?: number
}) {
  const gradientId = useId()
  const pts = values.map((v, i) => ({ v, i })).filter((p): p is { v: number; i: number } => p.v !== null)
  if (pts.length < 2) return <div style={{ height }} aria-hidden />

  const width = 200
  const pad = 3
  const min = Math.min(...pts.map((p) => p.v))
  const max = Math.max(...pts.map((p) => p.v))
  const span = max - min || 1
  const last = values.length - 1 || 1
  const x = (i: number) => (i / last) * width
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2)

  const line = pts.map((p, k) => `${k === 0 ? 'M' : 'L'}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const first = pts[0]!
  const end = pts[pts.length - 1]!
  const area = `${line} L${x(end.i).toFixed(1)},${height} L${x(first.i).toFixed(1)},${height} Z`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img" aria-label={label}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.22} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
