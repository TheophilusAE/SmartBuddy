import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { BrainCircuit, Cpu, History, House, LayoutDashboard, LogOut, Menu, Moon, SlidersHorizontal, Smile, Sun, X } from 'lucide-react'
import { useAuth } from '../auth'
import { useLive, usePrimaryDevice, type LinkState } from '../live'
import { ageSeconds, relative } from '../format'
import { useTheme } from '../theme'
import { GasBanner } from './status'
import { cx, StatusDot } from './ui'

const NAV = [
  { to: '/', label: 'Home', icon: LayoutDashboard, end: true },
  { to: '/control', label: 'Devices', icon: SlidersHorizontal, end: false },
  { to: '/history', label: 'History', icon: History, end: false },
  { to: '/comfort', label: 'Comfort', icon: Smile, end: false },
  { to: '/evaluation', label: 'Model', icon: BrainCircuit, end: false },
]

const LINK: Record<LinkState, { tone: 'good' | 'warn' | 'danger' | 'neutral'; text: string }> = {
  live: { tone: 'good', text: 'Connected' },
  polling: { tone: 'warn', text: 'Updating every 5 s' },
  unreachable: { tone: 'danger', text: 'Backend offline' },
  connecting: { tone: 'neutral', text: 'Connecting' },
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-accent-ink shadow-sm">
        <House className="h-[18px] w-[18px]" aria-hidden />
      </span>
      <span className="text-[17px] font-bold tracking-tight">SmartBuddy</span>
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cx(
              'flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[15px] transition-colors',
              isActive ? 'bg-accent font-semibold text-accent-ink shadow-sm' : 'text-ink-2 hover:bg-raised hover:text-ink',
            )
          }
        >
          <n.icon className="h-[18px] w-[18px]" aria-hidden />
          {n.label}
        </NavLink>
      ))}
    </nav>
  )
}

function DeviceCard() {
  const device = usePrimaryDevice()
  const { now } = useLive()
  const online = !!device?.online
  return (
    <div className="rounded-2xl border border-line bg-raised/60 p-3.5">
      <div className="flex items-center gap-2.5">
        <span className={cx('flex h-9 w-9 items-center justify-center rounded-xl', online ? 'bg-good/15 text-good' : 'bg-danger/15 text-danger')}>
          <Cpu className="h-[18px] w-[18px]" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            ESP32
            <span className={cx('rounded-full px-1.5 py-0.5 text-[11px] font-medium', online ? 'bg-good/15 text-good-ink' : 'bg-danger/15 text-danger-ink')}>
              {device ? (online ? 'Online' : 'Offline') : 'Not seen'}
            </span>
          </div>
          <div className="truncate text-xs text-muted">
            {device ? `Last seen ${relative(ageSeconds(device.last_seen_at, now))}` : 'Waiting for the first reading'}
          </div>
        </div>
      </div>
    </div>
  )
}

function ThemeToggle() {
  const [theme, toggle] = useTheme()
  return (
    <button
      type="button"
      onClick={toggle}
      className="flex items-center gap-1 rounded-full border border-line bg-surface p-1 shadow-sm"
      aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
    >
      <span className={cx('flex h-7 w-7 items-center justify-center rounded-full transition-colors', theme === 'light' ? 'bg-lux/20 text-lux' : 'text-muted')}>
        <Sun className="h-4 w-4" aria-hidden />
      </span>
      <span className={cx('flex h-7 w-7 items-center justify-center rounded-full transition-colors', theme === 'dark' ? 'bg-accent/25 text-accent' : 'text-muted')}>
        <Moon className="h-4 w-4" aria-hidden />
      </span>
    </button>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const { link, warnings } = useLive()
  const location = useLocation()
  const onHome = location.pathname === '/'
  const [drawer, setDrawer] = useState(false)
  const status = LINK[link]

  useEffect(() => setDrawer(false), [location.pathname])
  useEffect(() => {
    if (!drawer) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawer])

  const initial = (user?.username ?? '?').slice(0, 1).toUpperCase()

  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-sidebar px-4 py-6 lg:flex">
        <div className="px-2">
          <Logo />
        </div>
        <div className="mt-10">
          <NavItems />
        </div>
        <div className="mt-auto">
          <DeviceCard />
        </div>
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col bg-sidebar px-4 py-5 shadow-xl">
            <div className="flex items-center justify-between px-2">
              <Logo />
              <button type="button" onClick={() => setDrawer(false)} className="rounded-lg p-2 text-ink-2 hover:bg-raised" aria-label="Close menu">
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>
            <div className="mt-8">
              <NavItems onNavigate={() => setDrawer(false)} />
            </div>
            <div className="mt-auto">
              <DeviceCard />
            </div>
          </div>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-line bg-page/85 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6 lg:px-10">
            <button
              type="button"
              onClick={() => setDrawer(true)}
              className="rounded-lg p-2 text-ink-2 hover:bg-raised lg:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>
            <div className="lg:hidden">
              <Logo />
            </div>

            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <span className="hidden sm:inline-flex" role="status" title="Connection between this dashboard and the backend (the ESP32 status is in the sidebar)">
                <StatusDot tone={status.tone} pulse={link === 'live'}>{status.text}</StatusDot>
              </span>
              <ThemeToggle />
              <div className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-1 shadow-sm sm:pr-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-ink" aria-hidden>
                  {initial}
                </span>
                <span className="hidden text-sm font-medium sm:inline">{user?.username}</span>
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="rounded-full p-1.5 text-muted hover:bg-raised hover:text-ink"
                  aria-label="Sign out"
                  title="Sign out"
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-10">
          {!onHome && <GasBanner warnings={warnings} />}
          <Outlet />
          <footer className="mt-12 text-xs text-muted">
            SmartBuddy · academic AIoT project. Gas indication is experimental and not a safety device.
          </footer>
        </main>
      </div>
    </div>
  )
}
