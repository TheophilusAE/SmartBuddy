import { useEffect, useState } from 'react'
import { api, qs } from './api'
import type { SeriesPoint } from './types'

export const RANGES = [
  { id: '1h', label: '1h', ms: 3600e3 },
  { id: '6h', label: '6h', ms: 6 * 3600e3 },
  { id: '24h', label: '24h', ms: 24 * 3600e3 },
  { id: '7d', label: '7d', ms: 7 * 24 * 3600e3 },
] as const
export type RangeId = (typeof RANGES)[number]['id']

export function rangeMs(id: RangeId): number {
  return RANGES.find((r) => r.id === id)?.ms ?? 3600e3
}

export function useSeries(spanMs: number, includeSimulated: boolean, deviceId?: string) {
  const [points, setPoints] = useState<SeriesPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [span, setSpan] = useState({ start: Date.now() - spanMs, end: Date.now() })

  useEffect(() => {
    let cancelled = false
    const load = () => {
      const end = Date.now()
      const start = end - spanMs
      api<{ points: SeriesPoint[] }>(
        `/readings/series${qs({
          start: new Date(start).toISOString(),
          end: new Date(end).toISOString(),
          include_simulated: includeSimulated,
          device_id: deviceId,
        })}`,
      )
        .then((r) => {
          if (cancelled) return
          setPoints(r.points)
          setSpan({ start, end })
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }
    setLoading(true)
    load()
    const id = setInterval(load, 30000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [spanMs, includeSimulated, deviceId])

  return { points, loading, startMs: span.start, endMs: span.end }
}

export function trend(values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null)
  if (known.length < 2) return null
  return known[known.length - 1]! - known[0]!
}
