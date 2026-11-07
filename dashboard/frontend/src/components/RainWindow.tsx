import type { ReactNode } from 'react'
import { CloudRain, CloudSun, Info, Loader2, TriangleAlert } from 'lucide-react'
import { ageSeconds, relative } from '../format'
import { Card, cx, IconBubble } from './ui'
import type { DeviceState, RainStatus, Reading, WindowState } from '../types'

type Tone = 'good' | 'warn' | 'danger' | 'accent' | 'neutral'

const CHIP: Record<Tone, string> = {
  good: 'bg-good/15 text-good-ink',
  warn: 'bg-warn/15 text-warn-ink',
  danger: 'bg-danger/15 text-danger-ink',
  accent: 'bg-accent/15 text-accent',
  neutral: 'bg-raised text-ink-2',
}

export function rainView(status: RainStatus | null | undefined): { label: string; tone: Tone } {
  switch (status) {
    case 'rain':
      return { label: 'Rain detected', tone: 'warn' }
    case 'dry':
      return { label: 'Dry', tone: 'good' }
    case 'error':
      return { label: 'Sensor error', tone: 'danger' }
    case 'initializing':
      return { label: 'Starting', tone: 'neutral' }
    default:
      return { label: 'Not reported', tone: 'neutral' }
  }
}

export function windowView(state: WindowState | null | undefined): { label: string; tone: Tone } {
  switch (state) {
    case 'open':
      return { label: 'Open', tone: 'good' }
    case 'closed':
      return { label: 'Closed', tone: 'accent' }
    case 'moving':
      return { label: 'Moving', tone: 'warn' }
    case 'unknown':
      return { label: 'Unknown', tone: 'neutral' }
    default:
      return { label: 'Not reported', tone: 'neutral' }
  }
}

export function StateChip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide', CHIP[tone])}>{children}</span>
}

export function WindowGraphic({ state, className }: { state: WindowState | null | undefined; className?: string }) {
  const known = state === 'open' || state === 'closed' || state === 'moving'
  return (
    <svg viewBox="0 0 64 64" className={cx('h-16 w-16', state === 'moving' && 'animate-pulse', className)} aria-hidden>
      <rect x="6" y="6" width="52" height="52" rx="4" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray={known ? undefined : '5 4'} />
      {state === 'open' ? (
        <>
          <path d="M9 9 L23 15 L23 49 L9 55 Z" fill="currentColor" fillOpacity="0.15" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
          <path d="M55 9 L41 15 L41 49 L55 55 Z" fill="currentColor" fillOpacity="0.15" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
        </>
      ) : known ? (
        <>
          <rect x="10" y="10" width="44" height="44" rx="2" fill="currentColor" fillOpacity="0.15" />
          <line x1="32" y1="8" x2="32" y2="56" stroke="currentColor" strokeWidth="2.5" />
          <line x1="8" y1="32" x2="56" y2="32" stroke="currentColor" strokeWidth="2.5" />
        </>
      ) : (
        <text x="32" y="41" textAnchor="middle" fontSize="24" fontWeight="700" fill="currentColor">?</text>
      )}
    </svg>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-semibold tabular">{children}</dd>
    </div>
  )
}

export default function RainWindowCard({ reading, device, now }: { reading: Reading | null; device: DeviceState | null; now: number }) {
  const online = !!device?.online
  const reported = !!reading && (reading.rain_status !== null || reading.window_state !== null)
  const rain = rainView(reading?.rain_status)
  const win = windowView(reading?.window_state)
  const rainIcon =
    reading?.rain_status === 'rain' ? (
      <CloudRain className="h-5 w-5" aria-hidden />
    ) : reading?.rain_status === 'error' ? (
      <TriangleAlert className="h-5 w-5" aria-hidden />
    ) : reading?.rain_status === 'initializing' ? (
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
    ) : (
      <CloudSun className="h-5 w-5" aria-hidden />
    )

  const panel = (tone: Tone) =>
    cx(
      'rounded-2xl border p-4',
      tone === 'warn' ? 'border-warn/40 bg-warn/10' : tone === 'danger' ? 'border-danger/40 bg-danger/10' : 'border-line bg-raised/40',
    )

  return (
    <Card
      title="Rain & window protection"
      subtitle="The ESP32 closes the window by itself when it rains"
      action={device && !online ? <StateChip tone="danger">ESP32 offline</StateChip> : undefined}
    >
      {!reported || !reading ? (
        <p className="text-sm text-ink-2">
          No rain or window data yet. It appears once the ESP32 runs <code>New_Code.ino</code> v1.4.0 with the raindrop sensor on GPIO 32 and
          the servo on GPIO 33.
        </p>
      ) : (
        <>
          {!online && (
            <p className="mb-3 text-sm text-danger-ink">
              No new data from the ESP32. These are the last values it sent, {relative(ageSeconds(reading.received_at, now))}.
            </p>
          )}
          <div className={cx('grid grid-cols-1 gap-4 md:grid-cols-2', !online && 'opacity-60')}>
            <section className={panel(online ? rain.tone : 'neutral')} aria-label="Rain sensor">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <IconBubble hue={reading.rain_status === 'error' ? 'danger' : 'rain'}>{rainIcon}</IconBubble>
                  <div>
                    <div className="text-sm text-muted">Rain sensor</div>
                    <div className="text-xl font-bold">{rain.label}</div>
                  </div>
                </div>
                <StateChip tone={rain.tone}>{reading.rain_status === 'rain' ? 'Rain' : rain.label}</StateChip>
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
                <Fact label="Raw">{reading.rain_raw ?? '—'}</Fact>
                <Fact label="Filtered">{reading.rain_filtered ?? '—'}</Fact>
                <Fact label="Updated">{relative(ageSeconds(reading.received_at, now))}</Fact>
              </dl>
              {reading.rain_status === 'error' && (
                <p className="mt-3 text-xs text-danger-ink">Reading stuck at its limit. Check the AO wire on GPIO 32, 3.3 V and GND. The window keeps its position.</p>
              )}
            </section>

            <section className={panel('neutral')} aria-label="Automatic window">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <WindowGraphic state={reading.window_state} className={reading.window_state === 'closed' ? 'text-accent' : 'text-ink-2'} />
                  <div>
                    <div className="text-sm text-muted">Automatic window</div>
                    <div className="text-xl font-bold">{win.label}</div>
                  </div>
                </div>
                <StateChip tone={win.tone}>{win.label}</StateChip>
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
                <Fact label="Servo angle">{reading.servo_angle === null ? '—' : `${reading.servo_angle}°`}</Fact>
                <Fact label="Automation">{reading.window_auto === null ? '—' : reading.window_auto ? 'Enabled' : 'Disabled'}</Fact>
                <Fact label="Changed">{device?.window_changed_at ? relative(ageSeconds(device.window_changed_at, now)) : '—'}</Fact>
              </dl>
            </section>
          </div>
        </>
      )}
      <p className="mt-3 flex items-start gap-1.5 text-xs text-muted">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        Miniature demo model, not a weatherproofing or safety device. The angle is what the ESP32 sent to the servo; there's no sensor that
        confirms the window really moved.
      </p>
    </Card>
  )
}
