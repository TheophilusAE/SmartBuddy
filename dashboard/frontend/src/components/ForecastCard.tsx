import { useEffect, useRef, useState } from 'react'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { api } from '../api'
import { useLive } from '../live'
import { num } from '../format'
import { Card } from './ui'
import type { Forecast } from '../types'

const REFRESH_MS = 30_000
const WARM_C = 26

function Trend({ now, next }: { now: number; next: number }) {
  const d = next - now
  if (Math.abs(d) < 0.1) return <Minus className="h-4 w-4 text-muted" aria-hidden />
  return d > 0 ? <ArrowUpRight className="h-4 w-4 text-temp" aria-hidden /> : <ArrowDownRight className="h-4 w-4 text-hum" aria-hidden />
}

export default function ForecastCard() {
  const { reading } = useLive()
  const [fc, setFc] = useState<Forecast | null>(null)
  const last = useRef(0)

  useEffect(() => {
    if (Date.now() - last.current < REFRESH_MS) return
    last.current = Date.now()
    api<Forecast>('/ml/forecast')
      .then(setFc)
      .catch(() => setFc({ available: false, reason: 'Forecast unavailable right now' }))
  }, [reading?.id])

  const t = fc?.forecast?.temperature_c ?? null
  const h = fc?.forecast?.humidity_pct ?? null
  const nowT = fc?.now?.temperature_c ?? null
  const aiFan = reading?.fan_control === 'ai'

  return (
    <Card title="Room forecast" subtitle={fc?.available ? `ML prediction, ${fc.horizon_min} min ahead` : 'ML prediction'}>
      {!fc || !fc.available || t === null || nowT === null ? (
        <p className="text-sm text-muted">{fc?.reason ?? 'Loading…'}</p>
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-[32px] font-bold leading-none tabular">{num(t)} °C</span>
            {fc.uncertainty_c != null && <span className="text-sm text-muted tabular">± {num(fc.uncertainty_c, 2)}</span>}
            <Trend now={nowT} next={t} />
            <span className="text-sm text-muted tabular">now {num(nowT)} °C</span>
          </div>
          {h !== null && <p className="mt-1 text-sm text-ink-2 tabular">Humidity {num(h, 0)} %</p>}
          {aiFan ? (
            <p className="mt-3 text-sm text-good-ink">The AI controls the fan from this forecast.</p>
          ) : t > WARM_C && t > nowT && (
            <p className="mt-3 text-sm text-warn-ink">It's getting warm. Turning the fan on now may help.</p>
          )}
          <p className="mt-3 text-xs text-muted">Learned from your own past readings. Model {fc.model_version}.</p>
        </>
      )}
    </Card>
  )
}
