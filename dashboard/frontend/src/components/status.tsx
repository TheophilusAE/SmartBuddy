import { AlertTriangle, CircleDot, CloudOff, FlaskConical, Radio, RefreshCw, WifiOff } from 'lucide-react'
import { FRESH_SECONDS, useLive, type LinkState } from '../live'
import { ageSeconds, relative } from '../format'
import type { DeviceState, GasWarning, Reading } from '../types'
import { Badge } from './ui'

export function LinkPill({ link }: { link: LinkState }) {
  switch (link) {
    case 'live':
      return <Badge tone="good" icon={<Radio className="h-3 w-3" aria-hidden />}>Live updates</Badge>
    case 'polling':
      return <Badge tone="warn" icon={<RefreshCw className="h-3 w-3" aria-hidden />}>Live updates paused · polling</Badge>
    case 'unreachable':
      return <Badge tone="danger" icon={<CloudOff className="h-3 w-3" aria-hidden />}>Backend unreachable</Badge>
    default:
      return <Badge icon={<RefreshCw className="h-3 w-3 animate-spin" aria-hidden />}>Connecting</Badge>
  }
}

export type Freshness = 'none' | 'live' | 'stale' | 'offline'

export function freshnessOf(reading: Reading | null, device: DeviceState | null, now: number): Freshness {
  if (!reading) return 'none'
  if (device && !device.online) return 'offline'
  const age = ageSeconds(reading.received_at, now)
  return age !== null && age <= FRESH_SECONDS ? 'live' : 'stale'
}

export function DataSourceBadge({ reading, device }: { reading: Reading | null; device: DeviceState | null }) {
  const { now } = useLive()
  if (!reading) return <Badge icon={<CircleDot className="h-3 w-3" aria-hidden />}>No data yet</Badge>
  const fresh = freshnessOf(reading, device, now)
  const age = relative(ageSeconds(reading.received_at, now))
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {reading.is_simulated && (
        <Badge tone="accent" icon={<FlaskConical className="h-3 w-3" aria-hidden />}>Simulated data</Badge>
      )}
      {fresh === 'live' && <Badge tone="good" icon={<CircleDot className="h-3 w-3" aria-hidden />}>Live · {age}</Badge>}
      {fresh === 'stale' && <Badge tone="warn" icon={<AlertTriangle className="h-3 w-3" aria-hidden />}>Stale · {age}</Badge>}
      {fresh === 'offline' && <Badge tone="danger" icon={<WifiOff className="h-3 w-3" aria-hidden />}>Device offline · last data {age}</Badge>}
    </span>
  )
}

export function DeviceBadge({ device }: { device: DeviceState | null }) {
  const { now } = useLive()
  if (!device) return <Badge icon={<WifiOff className="h-3 w-3" aria-hidden />}>No device has connected</Badge>
  return device.online ? (
    <Badge tone="good" icon={<CircleDot className="h-3 w-3" aria-hidden />}>{device.device_id} online</Badge>
  ) : (
    <Badge tone="danger" icon={<WifiOff className="h-3 w-3" aria-hidden />}>
      {device.device_id} offline · seen {relative(ageSeconds(device.last_seen_at, now))}
    </Badge>
  )
}

export function GasBanner({ warnings }: { warnings: GasWarning[] }) {
  if (warnings.length === 0) return null
  const w = warnings[0]!
  const since = w.since
    ? new Date(w.since).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : null
  return (
    <div role="alert" className="mb-6 flex items-center gap-3 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger text-white">
        <AlertTriangle className="h-4 w-4" aria-hidden />
      </span>
      <p className="text-sm text-ink">
        <span className="font-semibold text-danger-ink">Gas / smoke alarm</span>
        <span className="text-ink-2">
          {' '}· MQ-2 reading {w.gas_adc ?? '—'}
          {since && <> since {since}</>}. Check the room.
        </span>
      </p>
    </div>
  )
}
