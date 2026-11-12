import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bot } from 'lucide-react'
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, errorMessage } from '../api'
import { useLive } from '../live'
import { num, shortTime } from '../format'
import { Badge, Button, Card, ErrorNote, Segmented, Stat } from './ui'
import type { ForecastHistory, Mode, ModeInfo } from '../types'

const FAN_ON_C = 26.1
const FAN_OFF_C = 25.5
const RANGES = [
  { id: '1', label: '1 h' },
  { id: '3', label: '3 h' },
  { id: '6', label: '6 h' },
  { id: '24', label: '24 h' },
] as const
type Range = (typeof RANGES)[number]['id']

interface Row {
  t: number
  actual?: number
  predicted?: number
  fanAi?: number
  fanRule?: number
}

function toRows(h: ForecastHistory | null): Row[] {
  if (!h) return []
  const rows = new Map<number, Row>()
  const at = (iso: string) => {
    const t = Math.round(Date.parse(iso) / 30_000) * 30_000
    if (!rows.has(t)) rows.set(t, { t })
    return rows.get(t)!
  }
  for (const f of h.fan) {
    const r = at(f.at)
    r.actual = f.temperature
    r.fanAi = f.on && f.control === 'ai' ? 1 : 0
    r.fanRule = f.on && f.control !== 'ai' ? 1 : 0
  }
  for (const p of h.points) {
    if (p.predicted !== null) at(p.target_at).predicted = p.predicted
  }
  return [...rows.values()].sort((a, b) => a.t - b.t)
}

export default function AiFanControl({ isAdmin }: { isAdmin: boolean }) {
  const { mode, setMode } = useLive()
  const [info, setInfo] = useState<ModeInfo | null>(null)
  const [hist, setHist] = useState<ForecastHistory | null>(null)
  const [hours, setHours] = useState<Range>('3')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<ModeInfo>('/mode').then(setInfo).catch(() => setInfo(null))
    api<ForecastHistory>(`/ml/forecast/history?hours=${hours}`)
      .then(setHist)
      .catch((e) => setError(errorMessage(e)))
  }, [hours])

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [load])

  const active = mode === 'ML_AUTOMATIC'
  const toggle = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api<{ mode: Mode }>('/mode', {
        method: 'PUT',
        body: { mode: active ? 'ML_RECOMMENDATION' : 'ML_AUTOMATIC' },
      })
      setMode(res.mode)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const rows = useMemo(() => toRows(hist), [hist])
  const last = hist?.points.length ? hist.points[hist.points.length - 1] : null
  const aiShare = hist && hist.fan.length ? hist.fan.filter((f) => f.control === 'ai').length / hist.fan.length : null
  const s = hist?.summary

  return (
    <Card
      title="AI fan control"
      subtitle="The forecast decides the fan: on when the room is predicted to reach 26.1 °C, off when it is predicted to stay at or below 25.5 °C"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-accent" aria-hidden />
          {active ? <Badge tone="good">AI controls the fan</Badge> : <Badge tone="neutral">Firmware rule controls the fan</Badge>}
        </div>
        {isAdmin && (
          <Button onClick={() => void toggle()} disabled={busy}>
            {active ? 'Back to the firmware rule' : 'Let the AI control the fan'}
          </Button>
        )}
      </div>
      {info && !info.ml_automatic_enabled && (
        <p className="mt-2 text-xs text-muted">AI control is switched off on the server (ENABLE_ML_AUTOMATIC=false).</p>
      )}
      {info && !info.forecast_available && (
        <p className="mt-2 text-xs text-muted">Train the forecast below first. AI control needs a model that beats the no-change baseline.</p>
      )}
      {error && <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>}

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Latest forecast" value={last?.predicted != null ? `${num(last.predicted)} °C` : '—'}
          hint={hist?.horizon_min ? `${hist.horizon_min} min ahead` : undefined} />
        <Stat label="AI decision" value={last?.decision ? `Fan ${last.decision}` : '—'}
          hint={last ? (last.mode === 'ML_AUTOMATIC' ? 'applied' : 'logged only') : undefined} />
        <Stat label="Live error (MAE)" value={s ? `${s.mae.toFixed(2)} °C` : '—'}
          hint={s ? `no change: ${s.mae_no_change.toFixed(2)} °C, n=${s.scored}` : 'needs finished forecasts'} />
        <Stat label="Fan under AI" value={aiShare === null ? '—' : `${Math.round(aiShare * 100)} %`} hint={`last ${hours} h`} />
      </div>

      <div className="mt-4 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Prediction history</span>
        <Segmented options={RANGES} value={hours} onChange={setHours} label="Time range" />
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No forecasts logged in this period yet.</p>
      ) : (
        <div className="mt-2 h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time"
                tickFormatter={(v: number) => shortTime(v, Number(hours) > 6)} stroke="var(--chart-axis)"
                tick={{ fill: 'var(--chart-label)', fontSize: 12 }} />
              <YAxis yAxisId="t" domain={['auto', 'auto']} stroke="var(--chart-axis)" tick={{ fill: 'var(--chart-label)', fontSize: 12 }}
                tickFormatter={(v: number) => v.toFixed(1)} />
              <YAxis yAxisId="fan" orientation="right" domain={[0, 4]} hide />
              <Tooltip labelFormatter={(v) => shortTime(Number(v), true)}
                formatter={(v: number, name: string) => (name.startsWith('Fan') ? (v ? 'on' : 'off') : `${v.toFixed(2)} °C`)} />
              <Legend />
              <ReferenceLine yAxisId="t" y={FAN_ON_C} stroke="var(--chart-temp)" strokeDasharray="4 4" />
              <ReferenceLine yAxisId="t" y={FAN_OFF_C} stroke="var(--chart-hum)" strokeDasharray="4 4" />
              <Area yAxisId="fan" type="stepAfter" dataKey="fanAi" name="Fan on (AI)" stroke="none" fill="var(--chart-gas)" fillOpacity={0.35} connectNulls isAnimationActive={false} />
              <Area yAxisId="fan" type="stepAfter" dataKey="fanRule" name="Fan on (rule)" stroke="none" fill="var(--chart-lux)" fillOpacity={0.35} connectNulls isAnimationActive={false} />
              <Line yAxisId="t" dataKey="actual" name="Measured" stroke="var(--chart-temp)" dot={false} strokeWidth={2} connectNulls isAnimationActive={false} />
              <Line yAxisId="t" dataKey="predicted" name="Predicted" stroke="var(--chart-hum)" dot={false} strokeWidth={2} strokeDasharray="5 3" connectNulls isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-3 text-xs text-muted">
        Predicted values are drawn at the time they are about. The ESP32 follows the AI only while the server keeps
        answering; after 30 s without an answer it goes back to its own 26.1 / 25.5 °C rule. A gas alarm never starts the fan.
      </p>
    </Card>
  )
}
