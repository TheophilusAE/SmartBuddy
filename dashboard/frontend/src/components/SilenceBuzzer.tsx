import { useCallback, useEffect, useState } from 'react'
import { BellOff, Bell } from 'lucide-react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { localTime } from '../format'
import { Button } from './ui'

interface MuteState {
  device_id: string
  muted_until: string | null
}

// silences the device buzzer for the current gas alarm (max 5 min); the alarm itself stays on
export default function SilenceBuzzer({ deviceId, alarmActive }: { deviceId: string; alarmActive: boolean }) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [until, setUntil] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<MuteState>(`/devices/buzzer/silence?device_id=${encodeURIComponent(deviceId)}`)
      .then((s) => setUntil(s.muted_until))
      .catch(() => setUntil(null))
  }, [deviceId])

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [load, alarmActive])

  const send = async (path: 'silence' | 'unmute') => {
    setBusy(true)
    setError(null)
    try {
      const s = await api<MuteState>(`/devices/buzzer/${path}`, { method: 'POST', body: { device_id: deviceId } })
      setUntil(s.muted_until)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  if (!alarmActive && !until) return null

  return (
    <div className="mt-3">
      {until ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
            <BellOff className="h-4 w-4" aria-hidden />
            Buzzer silenced until {localTime(until)}. The alarm is still active.
          </span>
          {isAdmin && (
            <Button onClick={() => void send('unmute')} disabled={busy}>
              <Bell className="h-4 w-4" aria-hidden /> Unmute
            </Button>
          )}
        </div>
      ) : isAdmin ? (
        <Button onClick={() => void send('silence')} disabled={busy}>
          <BellOff className="h-4 w-4" aria-hidden /> Silence buzzer (5 min)
        </Button>
      ) : (
        <p className="text-sm text-muted">Only an admin can silence the buzzer.</p>
      )}
      {error && <p className="mt-2 text-sm text-danger-ink">{error}</p>}
    </div>
  )
}
