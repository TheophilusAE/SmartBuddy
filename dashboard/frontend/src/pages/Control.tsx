import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Activity, AlertTriangle, BellOff, CheckCircle2, Clock, CloudRain, Cpu, Fan, Flame, Lightbulb, OctagonX, Sun, Thermometer, Wifi, Volume2, XCircle } from 'lucide-react'
import { api, ApiError, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useLive, usePrimaryDevice } from '../live'
import { ageSeconds, localTime, MODE_LABELS, num, relative } from '../format'
import { Badge, Button, Card, cx, EmptyState, ErrorNote, IconBubble, PageHeader, SectionTitle, type Hue } from '../components/ui'
import { rainView, StateChip, WindowGraphic, windowView } from '../components/RainWindow'
import type { CommandEvent, DeviceState, Mode, RainStatus, Reading, SensorState } from '../types'

type Switchable = 'fan' | 'light' | 'buzzer'
const FINAL = new Set(['acked', 'rejected', 'expired', 'superseded'])
const ACK_TIMEOUT_MS = 15000

interface Tracked {
  event: CommandEvent
  startedAt: number
  timedOut: boolean
}

function outcome(t: Tracked | undefined): ReactNode {
  if (!t) return null
  const e = t.event
  if (e.status === 'acked') {
    return <Badge tone="good" icon={<CheckCircle2 className="h-3 w-3" aria-hidden />}>Device confirmed {e.state} · {localTime(e.acked_at)}</Badge>
  }
  if (e.status === 'rejected') {
    return <Badge tone="danger" icon={<XCircle className="h-3 w-3" aria-hidden />}>Rejected by device{e.ack_reason ? `: ${e.ack_reason}` : ''}</Badge>
  }
  if (e.status === 'expired' || t.timedOut) {
    return <Badge tone="warn" icon={<Clock className="h-3 w-3" aria-hidden />}>No acknowledgement - state unchanged as far as we know</Badge>
  }
  if (e.status === 'superseded') return <Badge>Replaced by a newer command</Badge>
  return (
    <Badge tone="accent" icon={<Clock className="h-3 w-3 animate-pulse" aria-hidden />}>
      {e.status === 'sent' ? 'Delivered, waiting for confirmation' : 'Queued, waiting for device'}
    </Badge>
  )
}

function useCommandTracker() {
  const { commandUpdates } = useLive()
  const [tracked, setTracked] = useState<Record<string, Tracked>>({})
  const trackedRef = useRef(tracked)
  trackedRef.current = tracked

  useEffect(() => {
    setTracked((prev) => {
      let changed = false
      const next = { ...prev }
      for (const [key, t] of Object.entries(prev)) {
        const upd = commandUpdates[t.event.id]
        if (upd && upd.status !== t.event.status) {
          next[key] = { ...t, event: upd }
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [commandUpdates])

  useEffect(() => {
    const id = window.setInterval(() => {
      for (const [key, t] of Object.entries(trackedRef.current)) {
        if (FINAL.has(t.event.status) || t.timedOut) continue
        if (Date.now() - t.startedAt > ACK_TIMEOUT_MS) {
          setTracked((prev) => {
            const cur = prev[key]
            return cur ? { ...prev, [key]: { ...cur, timedOut: true } } : prev
          })
          continue
        }
        api<CommandEvent>(`/devices/commands/${t.event.id}`)
          .then((ev) =>
            setTracked((prev) => {
              const cur = prev[key]
              return cur && cur.event.id === ev.id ? { ...prev, [key]: { ...cur, event: ev } } : prev
            }),
          )
          .catch(() => undefined)
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [])

  const track = (key: string, event: CommandEvent) =>
    setTracked((prev) => ({ ...prev, [key]: { event, startedAt: Date.now(), timedOut: false } }))
  const busy = (key: string) => {
    const t = tracked[key]
    return !!t && !FINAL.has(t.event.status) && !t.timedOut
  }
  return { tracked, track, busy }
}

const ACTUATORS: { key: Switchable; label: string; icon: ReactNode; note: string }[] = [
  { key: 'fan', label: 'Fan', icon: <Fan className="h-5 w-5" aria-hidden />, note: 'DC fan through the driver transistor' },
  { key: 'light', label: 'LED', icon: <Lightbulb className="h-5 w-5" aria-hidden />, note: 'Ordinary LED, on/off only' },
  { key: 'buzzer', label: 'Buzzer', icon: <Volume2 className="h-5 w-5" aria-hidden />, note: 'Test beep, stops by itself after 10 s' },
]

const MODES: { mode: Mode; title: string; text: string }[] = [
  { mode: 'MANUAL', title: 'Manual', text: 'Only you switch things. No automation.' },
  { mode: 'RULE_BASED', title: 'Rule-based', text: 'Fixed thresholds with hysteresis (fan by temperature, LED by darkness + motion). Not ML.' },
  { mode: 'ML_RECOMMENDATION', title: 'ML recommendation', text: 'Default. Shows comfort estimates and suggestions; never switches anything.' },
  { mode: 'ML_AUTOMATIC', title: 'ML automatic', text: 'Applies ML suggestions. Disabled until a validated model exists and it is enabled in config.' },
]

function ControlPanel() {
  const { user } = useAuth()
  const { mode, warnings, setMode } = useLive()
  const device = usePrimaryDevice()
  const { tracked, track, busy } = useCommandTracker()
  const [error, setError] = useState<string | null>(null)
  const [confirmFan, setConfirmFan] = useState(false)
  const [confirmStop, setConfirmStop] = useState(false)
  const [modeBusy, setModeBusy] = useState<Mode | null>(null)

  const isAdmin = user?.role === 'admin'
  const online = !!device?.online
  const gasActive = !!device && warnings.some((w) => w.device_id === device.device_id)

  const send = async (target: Switchable, state: 'on' | 'off', acknowledgeGas = false) => {
    if (!device) return
    setError(null)
    try {
      const ev = await api<CommandEvent>('/devices/commands', {
        method: 'POST',
        body: { device_id: device.device_id, target, state, acknowledge_gas_warning: acknowledgeGas },
      })
      track(target, ev)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && target === 'fan' && state === 'on' && gasActive) {
        setConfirmFan(true)
        return
      }
      setError(errorMessage(err))
    }
  }

  const emergencyStop = async () => {
    if (!device) return
    setConfirmStop(false)
    setError(null)
    try {
      const ev = await api<CommandEvent>('/devices/emergency-stop', { method: 'POST', body: { device_id: device.device_id } })
      track('all', ev)
      setMode('MANUAL')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const muteAlarm = async () => {
    if (!device) return
    setError(null)
    try {
      const ev = await api<CommandEvent>('/devices/alarm/mute', { method: 'POST', body: { device_id: device.device_id } })
      track('alarm', ev)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const changeMode = async (m: Mode) => {
    setModeBusy(m)
    setError(null)
    try {
      const res = await api<{ mode: Mode }>('/mode', { method: 'PUT', body: { mode: m } })
      setMode(res.mode)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setModeBusy(null)
    }
  }

  if (!device) return null

  const disabledReason = !isAdmin ? 'Your account is read-only.' : !online ? 'The device is offline, so commands would not be delivered.' : null

  return (
    <>
      <p className="mb-4 text-sm text-ink-2">
        Commands go through the backend. A switch only shows as changed once the device confirms it.
      </p>

      {error && <div className="mb-4"><ErrorNote>{error}</ErrorNote></div>}
      {disabledReason && (
        <p className="mb-4 rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink-2">{disabledReason}</p>
      )}
      {mode && mode !== 'MANUAL' && isAdmin && (
        <p className="mb-4 text-sm text-ink-2">
          Mode is <strong>{MODE_LABELS[mode]}</strong>. A manual switch pauses automation for that actuator for 10 minutes.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {ACTUATORS.map((a) => {
          const reported = device.actuators[a.key]
          const pending = busy(a.key)
          const disabled = !!disabledReason || pending
          return (
            <Card key={a.key}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-raised text-ink-2">{a.icon}</span>
                  <div>
                    <div className="font-semibold">{a.label}</div>
                    <div className="text-xs text-muted">{a.note}</div>
                  </div>
                </div>
                {reported === null ? <Badge>Unknown</Badge> : reported ? <Badge tone="good">On</Badge> : <Badge>Off</Badge>}
              </div>
              <p className="mt-2 text-xs text-muted">Reported by device · {localTime(device.state_reported_at)}</p>

              <div className="mt-4 grid grid-cols-2 gap-2" role="group" aria-label={`${a.label} switch`}>
                <Button
                  variant={reported ? 'primary' : 'secondary'}
                  disabled={disabled}
                  busy={pending && tracked[a.key]?.event.state === 'on'}
                  onClick={() => void send(a.key, 'on')}
                  aria-pressed={reported === true}
                >
                  On
                </Button>
                <Button
                  variant={reported === false ? 'primary' : 'secondary'}
                  disabled={disabled}
                  busy={pending && tracked[a.key]?.event.state === 'off'}
                  onClick={() => void send(a.key, 'off')}
                  aria-pressed={reported === false}
                >
                  Off
                </Button>
              </div>
              <div className="mt-3 min-h-[24px]" aria-live="polite">{outcome(tracked[a.key])}</div>
              {a.key === 'fan' && gasActive && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-danger-ink">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  Gas warning active. Starting the fan needs your explicit confirmation.
                </p>
              )}
            </Card>
          )
        })}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Safety">
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" disabled={!isAdmin} onClick={() => setConfirmStop(true)}>
              <OctagonX className="h-4 w-4" aria-hidden />
              Emergency stop
            </Button>
            <Button disabled={!isAdmin || !online || !gasActive} onClick={() => void muteAlarm()}>
              <BellOff className="h-4 w-4" aria-hidden />
              Mute gas buzzer (2 min)
            </Button>
          </div>
          <div className="mt-3 space-y-1" aria-live="polite">
            {outcome(tracked.all)}
            {outcome(tracked.alarm)}
          </div>
          <p className="mt-3 text-xs text-muted">
            Emergency stop switches fan, LED and test buzzer off and sets the mode to Manual. If the device can't reach the
            backend for 30 s it switches the fan and LED off on its own.
          </p>
        </Card>

        <Card title="Operating mode">
          <fieldset className="space-y-2" disabled={!isAdmin}>
            <legend className="sr-only">Operating mode</legend>
            {MODES.map((m) => (
              <label
                key={m.mode}
                className={cx(
                  'flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2',
                  mode === m.mode ? 'border-accent bg-accent/5' : 'border-line',
                  !isAdmin && 'cursor-not-allowed opacity-70',
                )}
              >
                <input
                  type="radio"
                  name="mode"
                  className="mt-1"
                  checked={mode === m.mode}
                  onChange={() => void changeMode(m.mode)}
                  disabled={modeBusy !== null}
                />
                <span>
                  <span className="text-sm font-medium">{m.title}</span>
                  <span className="block text-xs text-ink-2">{m.text}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </Card>
      </div>

      {confirmFan && (
        <ConfirmDialog
          title="Start the fan during a gas warning?"
          confirmLabel="Yes, start the fan"
          onCancel={() => setConfirmFan(false)}
          onConfirm={() => {
            setConfirmFan(false)
            void send('fan', 'on', true)
          }}
        >
          A brushed DC motor can spark. Only start it if you have checked the room and know that ventilation with this fan
          is safe here. If you suspect a real gas leak, leave the area and follow local safety advice instead.
        </ConfirmDialog>
      )}
      {confirmStop && (
        <ConfirmDialog
          title="Emergency stop?"
          confirmLabel="Stop everything"
          danger
          onCancel={() => setConfirmStop(false)}
          onConfirm={() => void emergencyStop()}
        >
          Fan, LED and test buzzer will be switched off and automation set to Manual.
        </ConfirmDialog>
      )}
    </>
  )
}

const FIRMWARE_RULES: { key: Switchable; label: string; icon: ReactNode; rule: string }[] = [
  { key: 'fan', label: 'Fan', icon: <Fan className="h-5 w-5" aria-hidden />, rule: 'On above 26 °C, off again at 25.5 °C. Holds its state if the DHT22 reading is unavailable.' },
  { key: 'light', label: 'LED', icon: <Lightbulb className="h-5 w-5" aria-hidden />, rule: 'On when the light level is ≤ 30 %, off at ≥ 40 %.' },
  { key: 'buzzer', label: 'Buzzer', icon: <Volume2 className="h-5 w-5" aria-hidden />, rule: 'Beeps while the MQ-2 alarm is active: filtered ADC > 1800 for 3 s after warm-up, clears below 1700.' },
]

function MonitorOutputs({ device, gasActive, reading }: { device: DeviceState; gasActive: boolean; reading: Reading | null }) {
  const win = windowView(reading?.window_state ?? device.window_state)
  return (
    <>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {FIRMWARE_RULES.map((a) => {
          const on = device.actuators[a.key]
          return (
            <div key={a.key} className="rounded-card border border-line bg-surface p-5 shadow-card">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-3">
                  <IconBubble hue={on ? 'accent' : 'neutral'} size="lg">{a.icon}</IconBubble>
                  <div>
                    <div className="font-semibold">{a.label}</div>
                    <div className="text-xs text-muted">Reported {relative(ageSeconds(device.state_reported_at, Date.now()))}</div>
                  </div>
                </div>
                <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', on ? 'bg-good/15 text-good-ink' : 'bg-raised text-muted')}>
                  {on === null ? 'Unknown' : on ? 'On' : 'Off'}
                </span>
              </div>
              <p className="mt-4 rounded-xl bg-raised/60 px-3 py-2 text-sm text-ink-2">{a.rule}</p>
            </div>
          )
        })}
        <div className="rounded-card border border-line bg-surface p-5 shadow-card">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-3">
              <IconBubble hue={reading?.window_state === 'closed' ? 'accent' : 'neutral'} size="lg">
                <WindowGraphic state={reading?.window_state ?? device.window_state} className="h-7 w-7" />
              </IconBubble>
              <div>
                <div className="font-semibold">Window</div>
                <div className="text-xs text-muted">SG90 · GPIO 33</div>
              </div>
            </div>
            <StateChip tone={win.tone}>{win.label}</StateChip>
          </div>
          <div className="mt-3 text-sm text-ink-2">
            Servo angle <span className="font-semibold text-ink tabular">{reading?.servo_angle == null ? '—' : `${reading.servo_angle}°`}</span>
          </div>
          <p className="mt-3 rounded-xl bg-raised/60 px-3 py-2 text-sm text-ink-2">
            Closes after 2 s of rain, opens again after 10 s dry. Keeps its position if the rain sensor has an error.
          </p>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted">
        Monitor-only: this firmware switches its outputs by itself and can't receive commands. To change a rule, edit the
        thresholds at the top of <code>New_Code.ino</code> and upload it again.
      </p>
      {gasActive && (
        <p className="mt-2 flex items-start gap-1.5 text-sm text-danger-ink">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          The MQ-2 alarm is active on the device. The firmware never starts the fan because of gas.
        </p>
      )}
    </>
  )
}

function ConfirmDialog({
  title,
  children,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
}: {
  title: string
  children: ReactNode
  confirmLabel: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 px-4" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="w-full max-w-md rounded-card border border-line bg-surface p-5">
        <h2 id="confirm-title" className="flex items-center gap-2 font-semibold">
          <AlertTriangle className="h-5 w-5 text-danger-ink" aria-hidden />
          {title}
        </h2>
        <p className="mt-2 text-sm text-ink-2">{children}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button ref={cancelRef} type="button" onClick={onCancel} className="min-h-[40px] rounded-lg border border-line px-3.5 text-sm hover:bg-raised">
            Cancel
          </button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

type HealthTone = 'good' | 'warn' | 'danger' | 'neutral'
const HEALTH_CHIP: Record<HealthTone, string> = {
  good: 'bg-good/15 text-good-ink',
  warn: 'bg-warn/15 text-warn-ink',
  danger: 'bg-danger/15 text-danger-ink',
  neutral: 'bg-raised text-ink-2',
}

function sensorHealth(state: SensorState | undefined, online: boolean): { label: string; tone: HealthTone } {
  if (!online) return { label: 'Offline', tone: 'danger' }
  if (state === 'ok') return { label: 'Online', tone: 'good' }
  if (state === 'warming_up') return { label: 'Warming up', tone: 'warn' }
  if (state === 'error') return { label: 'Error', tone: 'danger' }
  return { label: 'Unknown', tone: 'neutral' }
}

function rainHealth(status: RainStatus | null | undefined, online: boolean): { label: string; tone: HealthTone } {
  if (!online) return { label: 'Offline', tone: 'danger' }
  if (status === 'dry' || status === 'rain') return { label: 'Online', tone: 'good' }
  if (status === 'initializing') return { label: 'Starting', tone: 'warn' }
  if (status === 'error') return { label: 'Error', tone: 'danger' }
  return { label: 'Not reported', tone: 'neutral' }
}

function DeviceTile({
  icon,
  hue,
  name,
  detail,
  health,
  value,
  seen,
}: {
  icon: ReactNode
  hue: Hue
  name: string
  detail: string
  health: { label: string; tone: HealthTone }
  value: ReactNode
  seen: string
}) {
  return (
    <div className="flex flex-col rounded-card border border-line bg-surface p-5 shadow-card transition-transform hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-3">
        <IconBubble hue={hue} size="lg">{icon}</IconBubble>
        <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', HEALTH_CHIP[health.tone])}>{health.label}</span>
      </div>
      <div className="mt-4 font-semibold">{name}</div>
      <div className="text-sm text-muted">{detail}</div>
      <div className="mt-3 text-lg font-semibold tabular">{value}</div>
      <div className="mt-auto pt-3 text-xs text-muted">Last reading {seen}</div>
    </div>
  )
}

export default function Devices() {
  const { reading, now, controlEnabled, warnings, stats } = useLive()
  const device = usePrimaryDevice()

  if (!device) {
    return (
      <>
        <PageHeader title="Your devices" subtitle="Monitor the ESP32 and everything connected to it." />
        <Card>
          <EmptyState icon={<Cpu className="h-6 w-6" aria-hidden />} title="No device has connected yet">
            Devices appear once the ESP32 sends its first reading over Wi-Fi.
          </EmptyState>
        </Card>
      </>
    )
  }

  const online = device.online
  const r = reading && reading.device_id === device.device_id ? reading : null
  const seen = relative(ageSeconds(r?.received_at ?? device.last_seen_at, now))
  const st = r?.sensor_status
  const gasActive = warnings.some((w) => w.device_id === device.device_id)

  return (
    <>
      <PageHeader title="Your devices" subtitle="Monitor the ESP32 and everything connected to it." />

      <SectionTitle>Controller</SectionTitle>
      <div className="rounded-card border border-line bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center gap-4">
          <IconBubble hue={online ? 'accent' : 'danger'} size="lg">
            <Cpu className="h-6 w-6" aria-hidden />
          </IconBubble>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">ESP32 main unit</span>
              <span className={cx('rounded-full px-2.5 py-1 text-xs font-semibold', online ? HEALTH_CHIP.good : HEALTH_CHIP.danger)}>
                {online ? 'Online' : 'Offline'}
              </span>
              {device.is_simulated && <Badge tone="accent">Simulated</Badge>}
            </div>
            <div className="text-sm text-muted">{device.device_id}</div>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted">Connection</dt>
              <dd className="flex items-center gap-1 font-medium"><Wifi className="h-3.5 w-3.5" aria-hidden /> Wi-Fi &middot; HTTP</dd>
            </div>
            <div>
              <dt className="text-muted">Last seen</dt>
              <dd className="font-medium">{relative(ageSeconds(device.last_seen_at, now))}</dd>
            </div>
            <div>
              <dt className="text-muted">Real readings</dt>
              <dd className="font-medium tabular">{(stats?.real_readings ?? 0).toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-muted">Outputs</dt>
              <dd className="font-medium">{controlEnabled ? 'Remote control' : 'Firmware rules'}</dd>
            </div>
          </dl>
        </div>
      </div>

      <SectionTitle hint="status from the latest reading">Sensors</SectionTitle>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <DeviceTile
          icon={<Thermometer className="h-6 w-6" aria-hidden />}
          hue="temp"
          name="DHT22"
          detail="Temperature & humidity · GPIO 5"
          health={sensorHealth(st?.dht, online)}
          value={r && r.temperature_c !== null ? `${num(r.temperature_c)} °C · ${num(r.humidity_pct, 0)} %` : '—'}
          seen={seen}
        />
        <DeviceTile
          icon={<Sun className="h-6 w-6" aria-hidden />}
          hue="lux"
          name="LDR"
          detail="Light level · GPIO 35"
          health={sensorHealth(st?.ldr, online)}
          value={r && r.light_pct !== null ? `${num(r.light_pct, 0)} % · raw ${r.ldr_raw}` : '—'}
          seen={seen}
        />
        <DeviceTile
          icon={<Activity className="h-6 w-6" aria-hidden />}
          hue="motion"
          name="PIR HC-SR501"
          detail="Motion · GPIO 27"
          health={sensorHealth(st?.pir, online)}
          value={r && r.motion_detected !== null ? (r.motion_detected ? 'Movement' : 'No movement') : '—'}
          seen={seen}
        />
        <DeviceTile
          icon={<Flame className="h-6 w-6" aria-hidden />}
          hue={gasActive ? 'danger' : 'gas'}
          name="MQ-2"
          detail="Gas / smoke indication · GPIO 34"
          health={gasActive && online ? { label: 'Alarm', tone: 'danger' } : sensorHealth(st?.mq2, online)}
          value={r && r.gas_adc !== null ? `${r.gas_adc} ADC` : '—'}
          seen={seen}
        />
        <DeviceTile
          icon={<CloudRain className="h-6 w-6" aria-hidden />}
          hue={r?.rain_status === 'error' ? 'danger' : 'rain'}
          name="Raindrop sensor"
          detail="Rain · GPIO 32"
          health={rainHealth(r?.rain_status, online)}
          value={r && r.rain_filtered !== null ? `${rainView(r.rain_status).label} · ${r.rain_filtered} ADC` : '—'}
          seen={seen}
        />
      </div>

      <SectionTitle hint={controlEnabled ? 'remote control enabled' : 'monitor-only'}>Outputs</SectionTitle>
      {controlEnabled ? <ControlPanel /> : <MonitorOutputs device={device} gasActive={gasActive} reading={r} />}
    </>
  )
}
