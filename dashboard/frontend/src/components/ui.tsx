import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}


export function Card({
  title,
  subtitle,
  action,
  children,
  className,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cx('rounded-card border border-line bg-surface p-5 shadow-card sm:p-6', className)}>
      {(title || action) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[26px] font-bold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-ink-2">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 mt-8 flex items-baseline justify-between gap-3 first:mt-0">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{children}</h2>
      {hint && <span className="text-sm text-muted">{hint}</span>}
    </div>
  )
}


type Tone = 'neutral' | 'good' | 'warn' | 'danger' | 'accent'

const toneClass: Record<Tone, string> = {
  neutral: 'bg-raised text-ink-2',
  good: 'bg-good/15 text-good-ink',
  warn: 'bg-warn/15 text-warn-ink',
  danger: 'bg-danger/15 text-danger-ink',
  accent: 'bg-accent/15 text-accent',
}

export function Badge({ tone = 'neutral', icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium', toneClass[tone])}>
      {icon}
      {children}
    </span>
  )
}

const dotClass: Record<Tone, string> = {
  neutral: 'bg-muted',
  good: 'bg-good',
  warn: 'bg-warn',
  danger: 'bg-danger',
  accent: 'bg-accent',
}

export function StatusDot({ tone, children, pulse = false }: { tone: Tone; children: ReactNode; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-2">
      <span className="relative flex h-2.5 w-2.5">
        {pulse && <span className={cx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', dotClass[tone])} />}
        <span className={cx('relative inline-flex h-2.5 w-2.5 rounded-full', dotClass[tone])} />
      </span>
      {children}
    </span>
  )
}

export type Hue = 'temp' | 'hum' | 'lux' | 'motion' | 'gas' | 'rain' | 'accent' | 'danger' | 'neutral'

const hueBubble: Record<Hue, string> = {
  temp: 'bg-temp/15 text-temp',
  hum: 'bg-hum/15 text-hum',
  lux: 'bg-lux/15 text-lux',
  motion: 'bg-motion/15 text-motion',
  gas: 'bg-gas/15 text-gas',
  rain: 'bg-rain/15 text-rain',
  accent: 'bg-accent/15 text-accent',
  danger: 'bg-danger/15 text-danger',
  neutral: 'bg-raised text-ink-2',
}

export function IconBubble({ hue, children, size = 'md' }: { hue: Hue; children: ReactNode; size?: 'sm' | 'md' | 'lg' }) {
  const box = size === 'sm' ? 'h-8 w-8 rounded-lg' : size === 'lg' ? 'h-12 w-12 rounded-2xl' : 'h-10 w-10 rounded-xl'
  return <span className={cx('flex shrink-0 items-center justify-center', box, hueBubble[hue])}>{children}</span>
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly { id: T; label: string }[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-full bg-raised p-1">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          aria-pressed={value === o.id}
          className={cx(
            'rounded-full px-3 py-1 text-sm transition-colors',
            value === o.id ? 'bg-accent font-medium text-accent-ink shadow-sm' : 'text-ink-2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function ProgressRing({
  value,
  size = 132,
  stroke = 12,
  colorClass = 'text-accent',
  children,
}: {
  value: number
  size?: number
  stroke?: number
  colorClass?: string
  children?: ReactNode
}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.min(1, Math.max(0, value))
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-raised" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v)}
          className={cx('transition-[stroke-dashoffset] duration-700', colorClass)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('skeleton', className)} aria-hidden />
}


type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const variantClass: Record<Variant, string> = {
  primary: 'bg-accent text-accent-ink hover:bg-accent/90 border-transparent shadow-sm',
  secondary: 'bg-surface text-ink hover:bg-raised border-line',
  danger: 'bg-danger text-white hover:bg-danger/90 border-transparent',
  ghost: 'bg-transparent text-ink-2 hover:bg-raised border-transparent',
}

export function Button({
  variant = 'secondary',
  busy = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        'inline-flex min-h-[40px] items-center justify-center gap-2 rounded-xl border px-4 text-sm font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        variantClass[variant],
        className,
      )}
    >
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}…
    </div>
  )
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line px-4 py-10 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger-ink">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      {icon}
      <div className="min-w-0">
        <div className="text-sm text-muted">{label}</div>
        <div className="mt-0.5 truncate text-xl font-semibold text-ink">{value}</div>
        {hint && <div className="text-xs text-muted">{hint}</div>}
      </div>
    </div>
  )
}
