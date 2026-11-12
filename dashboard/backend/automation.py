from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from .config import Settings
from .schemas import OperatingMode

DEFAULT_MODE = OperatingMode.ML_RECOMMENDATION
MANUAL_OVERRIDE_S = 600


@dataclass
class ProposedAction:
    target: str
    state: str
    source: str
    reason: str


class AutomationEngine:
    def __init__(self, settings: Settings):
        self.s = settings
        self._blocked_until: dict[tuple[str, str], float] = {}
        self._last_motion: dict[str, float] = {}
        self._lock = threading.Lock()

    def _cooled_down(self, device_id: str, target: str, now: float) -> bool:
        return now >= self._blocked_until.get((device_id, target), 0.0)

    def mark_action(self, device_id: str, target: str) -> None:
        with self._lock:
            self._blocked_until[(device_id, target)] = time.monotonic() + self.s.automation_cooldown_s

    def mark_manual_override(self, device_id: str, targets: list[str]) -> None:
        until = time.monotonic() + MANUAL_OVERRIDE_S
        with self._lock:
            for t in targets:
                self._blocked_until[(device_id, t)] = until

    def evaluate(
        self,
        reading: dict[str, Any],
        mode: OperatingMode,
    ) -> list[ProposedAction]:
        device_id = reading["device_id"]
        now = time.monotonic()
        with self._lock:
            if reading.get("motion_detected"):
                self._last_motion[device_id] = now

            if mode != OperatingMode.RULE_BASED:
                return []

            actuators = reading.get("actuators") or {}
            wanted = self._rules(reading, device_id, now)

            out = []
            for action in wanted:
                current = actuators.get(action.target)
                if current is not None and current == (action.state == "on"):
                    continue
                if not self._cooled_down(device_id, action.target, now):
                    continue
                out.append(action)
            return out

    def _rules(self, reading: dict[str, Any], device_id: str, now: float) -> list[ProposedAction]:
        s = self.s
        out: list[ProposedAction] = []

        temp = reading.get("temperature_c")
        if temp is not None:
            if temp >= s.fan_on_temp_c:
                out.append(ProposedAction("fan", "on", "rule", f"temperature {temp:.1f} C >= {s.fan_on_temp_c} C"))
            elif temp <= s.fan_off_temp_c:
                out.append(ProposedAction("fan", "off", "rule", f"temperature {temp:.1f} C <= {s.fan_off_temp_c} C"))

        light = reading.get("light_pct")
        pir_ok = (reading.get("sensor_status") or {}).get("pir") == "ok"
        if light is not None and pir_ok:
            last_motion = self._last_motion.get(device_id)
            recent = last_motion is not None and now - last_motion <= s.motion_hold_s
            if recent and light <= s.light_on_pct:
                out.append(ProposedAction("light", "on", "rule", f"dark ({light:.0f} % light) and recent motion"))
            elif light >= s.light_off_pct:
                out.append(ProposedAction("light", "off", "rule", f"bright enough ({light:.0f} % light)"))
            elif not recent:
                out.append(ProposedAction("light", "off", "rule", "no motion recently"))
        return out


def mode_allowed(mode: OperatingMode, settings: Settings, model_available: bool) -> Optional[str]:
    if mode == OperatingMode.ML_AUTOMATIC:
        if not settings.enable_ml_automatic:
            return "ML_AUTOMATIC is disabled (set ENABLE_ML_AUTOMATIC=true after validating the model)"
        if not model_available:
            return "ML_AUTOMATIC needs a trained forecast model that beats the no-change baseline"
    return None
