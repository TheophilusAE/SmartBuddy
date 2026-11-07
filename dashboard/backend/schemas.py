from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .timeutil import parse_iso

DeviceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{3,32}$")]
BootId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")]
ShortText = Annotated[str, StringConstraints(max_length=64, pattern=r"^[\x20-\x7E]*$")]

Temperature = Annotated[float, Field(ge=-40, le=80, allow_inf_nan=False)]
Humidity = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
LightPct = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
AdcCount = Annotated[int, Field(ge=0, le=4095)]
ServoAngle = Annotated[int, Field(ge=0, le=180)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OperatingMode(str, Enum):
    MANUAL = "MANUAL"
    RULE_BASED = "RULE_BASED"
    ML_RECOMMENDATION = "ML_RECOMMENDATION"
    ML_AUTOMATIC = "ML_AUTOMATIC"


SensorHealth = Literal["ok", "error", "warming_up"]
RainStatus = Literal["initializing", "dry", "rain", "error"]
WindowState = Literal["open", "closed", "moving", "unknown"]


class SensorStatus(Strict):
    dht: SensorHealth
    ldr: SensorHealth
    pir: SensorHealth
    mq2: SensorHealth


class ActuatorLevels(Strict):
    fan: bool
    light: bool
    buzzer: bool


class ReadingIn(Strict):
    device_id: DeviceId
    boot_id: BootId
    sequence: Annotated[int, Field(ge=0, le=4_294_967_295)]
    timestamp: Optional[Annotated[str, StringConstraints(max_length=40)]]
    uptime_ms: Annotated[int, Field(ge=0, le=2**53)]
    temperature_c: Optional[Temperature]
    humidity_pct: Optional[Humidity]
    light_pct: Optional[LightPct]
    ldr_raw: Optional[AdcCount]
    motion_detected: Optional[bool]
    gas_adc: Optional[AdcCount]
    gas_warning_local: bool
    sensor_status: SensorStatus
    actuators: ActuatorLevels
    source: Literal["device", "simulator"]
    # rain sensor + window servo, None when the firmware doesn't have them
    rain_raw: Optional[AdcCount] = None
    rain_filtered: Optional[AdcCount] = None
    rain_status: Optional[RainStatus] = None
    window_state: Optional[WindowState] = None
    servo_angle: Optional[ServoAngle] = None
    window_auto: Optional[bool] = None

    @field_validator("timestamp")
    @classmethod
    def _check_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parse_iso(v)
        return v

    @model_validator(mode="after")
    def _status_matches_values(self) -> "ReadingIn":
        st = self.sensor_status
        pairs = [
            (st.dht, [self.temperature_c, self.humidity_pct], "dht"),
            (st.ldr, [self.light_pct, self.ldr_raw], "ldr"),
            (st.pir, [self.motion_detected], "pir"),
            (st.mq2, [self.gas_adc], "mq2"),
        ]
        for status, values, name in pairs:
            if status == "ok" and any(v is None for v in values):
                raise ValueError(f"{name} status is ok but a value is missing")
            if status != "ok" and any(v is not None for v in values):
                raise ValueError(f"{name} status is {status} but a value was sent")
        if self.rain_status in ("dry", "rain") and self.rain_filtered is None:
            raise ValueError("rain status needs rain_filtered")
        if self.window_state in ("open", "closed", "moving") and self.servo_angle is None:
            raise ValueError("window state needs servo_angle")
        if self.window_state in (None, "unknown") and self.servo_angle is not None:
            raise ValueError("servo_angle sent without a known window state")
        return self


class AckIn(Strict):
    device_id: DeviceId
    command_id: Annotated[int, Field(ge=1, le=2**53)]
    result: Literal["applied", "rejected", "expired"]
    reason: Optional[ShortText] = None
    observed: ActuatorLevels


class LoginIn(Strict):
    username: Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class CommandIn(Strict):
    device_id: DeviceId
    target: Literal["fan", "light", "buzzer"]
    state: Literal["on", "off"]
    acknowledge_gas_warning: bool = False


class DeviceOnlyIn(Strict):
    device_id: DeviceId


class ModeIn(Strict):
    mode: Literal["MANUAL", "RULE_BASED", "ML_RECOMMENDATION", "ML_AUTOMATIC"]


class FeedbackIn(Strict):
    rating: Annotated[int, Field(ge=1, le=5)]
    device_id: Optional[DeviceId] = None
    note: Optional[Annotated[str, StringConstraints(max_length=200)]] = None

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = "".join(ch for ch in v if ch.isprintable()).strip()
        return v or None


class ReadingOut(BaseModel):
    id: int
    device_id: str
    sequence: int
    measured_at: str
    received_at: str
    timestamp_trusted: bool
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    light_pct: Optional[float]
    ldr_raw: Optional[int]
    motion_detected: Optional[bool]
    gas_adc: Optional[int]
    gas_warning_local: bool
    sensor_status: dict[str, str]
    valid: bool
    out_of_order: bool
    is_simulated: bool
