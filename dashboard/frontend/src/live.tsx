import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from './api'
import type { CommandEvent, DeviceState, GasWarning, Mode, Reading, Stats } from './types'


export type LinkState = 'connecting' | 'live' | 'polling' | 'unreachable'

interface LiveState {
  link: LinkState
  reading: Reading | null
  devices: DeviceState[]
  warnings: GasWarning[]
  mode: Mode | null
  stats: Stats | null
  controlEnabled: boolean
  commandUpdates: Record<number, CommandEvent>
  now: number
  refresh: () => Promise<void>
  setMode: (m: Mode) => void
}

const LiveContext = createContext<LiveState | null>(null)

interface StateResponse {
  devices: DeviceState[]
  mode: Mode
  warnings: GasWarning[]
  device_control_enabled: boolean
}

type WsMessage =
  | { type: 'reading'; data: Reading }
  | { type: 'device_state'; data: DeviceState }
  | { type: 'command_update'; data: CommandEvent }
  | { type: 'warning'; data: GasWarning }
  | { type: 'mode'; data: { mode: Mode } }

export function LiveProvider({ children }: { children: ReactNode }) {
  const [link, setLink] = useState<LinkState>('connecting')
  const [reading, setReading] = useState<Reading | null>(null)
  const [devices, setDevices] = useState<DeviceState[]>([])
  const [warnings, setWarnings] = useState<GasWarning[]>([])
  const [mode, setMode] = useState<Mode | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [controlEnabled, setControlEnabled] = useState(false)
  const [commandUpdates, setCommandUpdates] = useState<Record<number, CommandEvent>>({})
  const [now, setNow] = useState(() => Date.now())
  const wsOpen = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const [latest, state, st] = await Promise.all([
        api<{ reading: Reading | null }>('/readings/latest'),
        api<StateResponse>('/devices/state'),
        api<Stats>('/stats'),
      ])
      setReading(latest.reading)
      setDevices(state.devices)
      setMode(state.mode)
      setWarnings(state.warnings)
      setControlEnabled(state.device_control_enabled)
      setStats(st)
      if (!wsOpen.current) setLink('polling')
    } catch {
      if (!wsOpen.current) setLink('unreachable')
    }
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry = 1000
    let reconnectTimer: number | undefined
    let pingTimer: number | undefined
    let stopped = false

    const handle = (msg: WsMessage) => {
      switch (msg.type) {
        case 'reading':
          setReading((prev) => {
            if (prev && !prev.is_simulated && msg.data.is_simulated) return prev
            return msg.data
          })
          break
        case 'device_state':
          setDevices((prev) => {
            const rest = prev.filter((d) => d.device_id !== msg.data.device_id)
            return [...rest, msg.data].sort((a, b) => Number(a.is_simulated) - Number(b.is_simulated) || a.device_id.localeCompare(b.device_id))
          })
          break
        case 'command_update':
          setCommandUpdates((prev) => ({ ...prev, [msg.data.id]: msg.data }))
          break
        case 'warning':
          setWarnings((prev) => {
            const rest = prev.filter((w) => w.device_id !== msg.data.device_id)
            return msg.data.active ? [...rest, msg.data] : rest
          })
          break
        case 'mode':
          setMode(msg.data.mode)
          break
      }
    }

    const connect = () => {
      if (stopped) return
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/ws/live`)
      ws.onopen = () => {
        wsOpen.current = true
        retry = 1000
        setLink('live')
        void refresh()
        pingTimer = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25000)
      }
      ws.onmessage = (ev: MessageEvent) => {
        if (typeof ev.data !== 'string' || ev.data === 'pong') return
        try {
          handle(JSON.parse(ev.data) as WsMessage)
        } catch {
          // bad frame, skip
        }
      }
      ws.onclose = () => {
        wsOpen.current = false
        window.clearInterval(pingTimer)
        if (stopped) return
        setLink((l) => (l === 'unreachable' ? l : 'polling'))
        reconnectTimer = window.setTimeout(connect, retry)
        retry = Math.min(retry * 2, 30000)
      }
    }

    void refresh()
    connect()
    let ticks = 0
    const poll = window.setInterval(() => {
      ticks += 1
      if (!wsOpen.current || ticks % 3 === 0) void refresh()
    }, 5000)

    return () => {
      stopped = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(pingTimer)
      window.clearInterval(poll)
      ws?.close()
    }
  }, [refresh])

  const value = useMemo(
    () => ({ link, reading, devices, warnings, mode, stats, controlEnabled, commandUpdates, now, refresh, setMode }),
    [link, reading, devices, warnings, mode, stats, controlEnabled, commandUpdates, now, refresh],
  )
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}

export function useLive(): LiveState {
  const ctx = useContext(LiveContext)
  if (!ctx) throw new Error('useLive outside LiveProvider')
  return ctx
}

export function usePrimaryDevice(): DeviceState | null {
  const { devices } = useLive()
  return devices.find((d) => !d.is_simulated) ?? devices[0] ?? null
}

export const FRESH_SECONDS = 15
