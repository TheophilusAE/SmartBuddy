export type SensorState = 'ok' | 'error' | 'warming_up'
export type RainStatus = 'initializing' | 'dry' | 'rain' | 'error'
export type WindowState = 'open' | 'closed' | 'moving' | 'unknown'
export type Mode = 'MANUAL' | 'RULE_BASED' | 'ML_RECOMMENDATION' | 'ML_AUTOMATIC'
export type Target = 'fan' | 'light' | 'buzzer' | 'alarm' | 'all'
export type CommandStatus = 'pending' | 'sent' | 'acked' | 'rejected' | 'expired' | 'superseded'
export type Role = 'admin' | 'viewer'

export interface Actuators {
  fan: boolean | null
  light: boolean | null
  buzzer: boolean | null
}

export interface Reading {
  id: number
  device_id: string
  sequence: number
  measured_at: string
  received_at: string
  timestamp_trusted: boolean
  temperature_c: number | null
  humidity_pct: number | null
  light_pct: number | null
  ldr_raw: number | null
  motion_detected: boolean | null
  gas_adc: number | null
  gas_warning_local: boolean
  sensor_status: { dht: SensorState; ldr: SensorState; pir: SensorState; mq2: SensorState }
  actuators: Actuators
  valid: boolean
  out_of_order: boolean
  is_simulated: boolean
  rain_raw: number | null
  rain_filtered: number | null
  rain_status: RainStatus | null
  window_state: WindowState | null
  servo_angle: number | null
  window_auto: boolean | null
  fan_control?: 'rule' | 'ai' | null
}

export interface CommandEvent {
  id: number
  device_id: string
  target: Target
  state: 'on' | 'off' | 'mute'
  source: 'user' | 'rule' | 'ml' | 'safety' | 'system'
  requested_by: string | null
  reason: string | null
  status: CommandStatus
  created_at: string
  expires_at: string
  sent_at: string | null
  acked_at: string | null
  result: 'applied' | 'rejected' | 'expired' | null
  ack_reason: string | null
  observed: { fan: boolean; light: boolean; buzzer: boolean } | null
}

export interface DeviceState {
  device_id: string
  is_simulated: boolean
  online: boolean
  last_seen_at: string | null
  state_reported_at: string | null
  actuators: Actuators
  gas_warning_local: boolean
  rain_status: RainStatus | null
  rain_changed_at: string | null
  window_state: WindowState | null
  window_changed_at: string | null
  pending_commands: CommandEvent[]
}

export interface GasWarning {
  kind: 'gas'
  device_id: string
  active: boolean
  since: string | null
  gas_adc: number | null
  raised_by: string[]
}

export interface Stats {
  real_readings: number
  real_valid_readings: number
  real_valid_trusted_time: number
  real_incomplete_readings: number
  simulated_readings: number
  untrusted_timestamps: number
  out_of_order: number
  rejected_invalid: number
  rejected_duplicate: number
  rejected_unauthorized: number
  rejected_too_large: number
  rejected_rate_limited: number
  first_real_at: string | null
  last_real_at: string | null
  target_valid_readings: number
  feedback_total: number
  feedback_usable_for_ml: number
}

export interface SeriesPoint {
  t: number
  temperature_c: number | null
  humidity_pct: number | null
  light_pct: number | null
  gas_adc_max: number | null
  motion_any: boolean | null
  samples: number
}

export interface Advice {
  available: boolean
  reason?: string
  basis?: 'general' | 'model'
  headline?: string
  tips?: string[]
  suggested_actions?: Record<string, string>
  disclaimer?: string
  estimate?: number | null
  model_version?: string | null
  based_on_simulated_data?: boolean
}

export interface MlStatus {
  model_available: boolean
  model_version: string | null
  algorithm: string | null
  load_error: string | null
  usable_feedback: number
  usable_sessions: number
  min_labels: number
  min_sessions: number
  last_training: { status: string; attempted_at: string; message?: string } | null
  forecast_available: boolean
  forecast_version: string | null
}

export interface Forecast {
  available: boolean
  reason?: string
  model_version?: string
  horizon_min?: number
  uncertainty_c?: number | null
  based_on?: string
  now?: { temperature_c: number; humidity_pct: number }
  forecast?: { temperature_c: number | null; humidity_pct: number | null }
}

export interface ForecastResult {
  status: 'deployed' | 'no_improvement' | 'insufficient_data'
  attempted_at: string
  message?: string
  model_version?: string
  algorithm?: string
  horizon_min: number
  features: string[]
  summary: { readings: number; hours_recorded: number; segments: number; samples: number; days: string[] }
  split?: { method: string; train_rows: number; test_rows: number; train_until: string; test_from: string; test_to: string }
  metrics?: Record<string, Record<string, MetricPair>>
  best_candidate?: Record<string, string>
  beats_baseline?: Record<string, boolean>
  test_series?: { at: string; now: number; actual: number; predicted: number }[]
  limitations?: string[]
  refit_on_all_rows?: boolean
}

export interface MetricPair {
  mae: number
  rmse: number
}

export interface TrainingResult {
  status: 'deployed' | 'no_improvement' | 'insufficient_data'
  attempted_at: string
  message?: string
  model_version?: string
  algorithm?: string
  features: string[]
  summary: {
    dataset: string
    rows: number
    sessions: number
    rating_counts: Record<string, number>
    sources: Record<string, number>
  }
  requirements: { min_labels: number; min_sessions: number }
  split?: {
    method: string
    test_size: number
    random_state: number
    train_rows: number
    test_rows: number
    train_sessions: number
    test_sessions: number
  }
  metrics?: Record<string, MetricPair>
  best_candidate?: string
  beats_baseline?: boolean
  test_predictions?: { actual: number; predicted: number; baseline: number }[]
  limitations?: string[]
  refit_on_all_rows?: boolean
}

export interface FeedbackItem {
  id: number
  created_at: string
  username: string | null
  rating: number
  temperature_c: number | null
  humidity_pct: number | null
  light_pct: number | null
  motion_detected: boolean | null
  context_simulated: boolean
  note: string | null
}

export interface ModeInfo {
  mode: Mode
  ml_automatic_enabled: boolean
  device_control_enabled: boolean
  model_available: boolean
  forecast_available: boolean
}

export interface ForecastPoint {
  made_at: string
  target_at: string
  now: number
  predicted: number | null
  actual: number | null
  decision: 'on' | 'off' | null
  mode: Mode
  model_version: string
}

export interface FanSample {
  at: string
  temperature: number
  on: boolean
  control: 'rule' | 'ai' | null
}

export interface ForecastHistory {
  hours: number
  horizon_min: number | null
  points: ForecastPoint[]
  fan: FanSample[]
  summary: { scored: number; mae: number; mae_no_change: number } | null
}
