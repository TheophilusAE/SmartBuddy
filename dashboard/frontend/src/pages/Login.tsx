import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { Activity, Droplets, Eye, EyeOff, Flame, House, Lock, Sun, Thermometer, User } from 'lucide-react'
import { useAuth } from '../auth'
import { errorMessage } from '../api'
import { Button, ErrorNote } from '../components/ui'

const SENSORS: { label: string; icon: ReactNode; tint: string; color: string }[] = [
  { label: 'Temperature', icon: <Thermometer className="h-5 w-5" aria-hidden />, tint: 'bg-temp/15', color: 'text-temp' },
  { label: 'Humidity', icon: <Droplets className="h-5 w-5" aria-hidden />, tint: 'bg-hum/15', color: 'text-hum' },
  { label: 'Light', icon: <Sun className="h-5 w-5" aria-hidden />, tint: 'bg-lux/15', color: 'text-lux' },
  { label: 'Motion', icon: <Activity className="h-5 w-5" aria-hidden />, tint: 'bg-motion/15', color: 'text-motion' },
  { label: 'Gas / smoke', icon: <Flame className="h-5 w-5" aria-hidden />, tint: 'bg-gas/15', color: 'text-gas' },
]

function Field({
  id,
  label,
  icon,
  children,
}: {
  id: string
  label: string
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-muted">{icon}</span>
        {children}
      </div>
    </div>
  )
}

const inputClass =
  'h-12 w-full rounded-xl border border-line bg-surface pl-11 pr-4 text-[15px] text-ink placeholder:text-muted ' +
  'transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/15'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(errorMessage(err))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  const checkCaps = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState('CapsLock'))

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border border-line bg-surface shadow-[0_8px_30px_rgba(30,41,59,0.06)] md:grid-cols-2">
        <aside className="hidden flex-col justify-between bg-accent/10 p-10 md:flex">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent text-accent-ink">
              <House className="h-5 w-5" aria-hidden />
            </span>
            <span className="text-xl font-semibold tracking-tight">SmartBuddy</span>
          </div>

          <div>
            <h2 className="text-2xl font-semibold leading-snug tracking-tight">
              Your room at a glance.
            </h2>
            <p className="mt-2 text-ink-2">
              Temperature, humidity, light, motion and gas readings from your ESP32, all in one simple place.
            </p>
            <ul className="mt-6 flex flex-wrap gap-2" aria-label="Sensors">
              {SENSORS.map((s) => (
                <li key={s.label} className="flex items-center gap-2 rounded-full bg-surface/80 py-1.5 pl-1.5 pr-3 text-sm text-ink-2">
                  <span className={`flex h-7 w-7 items-center justify-center rounded-full ${s.tint} ${s.color}`}>{s.icon}</span>
                  {s.label}
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs text-muted">Runs only on this computer. Gas indication is not a safety device.</p>
        </aside>

        <div className="p-8 sm:p-10">
          <div className="mb-8 flex items-center gap-3 md:hidden">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent text-accent-ink">
              <House className="h-5 w-5" aria-hidden />
            </span>
            <span className="text-xl font-semibold tracking-tight">SmartBuddy</span>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
          <p className="mt-1 text-ink-2">Sign in to see your room.</p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            <Field id="username" label="Username" icon={<User className="h-[18px] w-[18px]" aria-hidden />}>
              <input
                id="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                maxLength={32}
                required
                placeholder="e.g. admin"
                className={inputClass}
              />
            </Field>

            <Field id="password" label="Password" icon={<Lock className="h-[18px] w-[18px]" aria-hidden />}>
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyUp={checkCaps}
                onKeyDown={checkCaps}
                maxLength={128}
                required
                placeholder="Your password"
                className={`${inputClass} pr-12`}
                aria-describedby={capsLock ? 'caps-warning' : undefined}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-2 my-auto flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-raised hover:text-ink"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
              >
                {showPassword ? <EyeOff className="h-[18px] w-[18px]" aria-hidden /> : <Eye className="h-[18px] w-[18px]" aria-hidden />}
              </button>
            </Field>
            {capsLock && (
              <p id="caps-warning" className="-mt-3 text-sm text-warn-ink" role="status">
                Caps Lock is on.
              </p>
            )}

            {error && <ErrorNote>{error}</ErrorNote>}

            <Button type="submit" variant="primary" busy={busy} className="h-12 w-full rounded-xl text-[15px]">
              Sign in
            </Button>
          </form>

          <p className="mt-6 text-sm text-muted">
            Forgot the password? Create a new one with <code className="rounded bg-raised px-1.5 py-0.5 text-xs">scripts/hash_password.py</code> and
            restart the backend.
          </p>
        </div>
      </div>
    </div>
  )
}
