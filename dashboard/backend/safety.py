from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Optional

from .timeutil import to_iso, utc_now


@dataclass
class GasState:
    active: bool = False
    since: Optional[str] = None
    gas_adc: Optional[int] = None
    device_flag: bool = False
    backend_flag: bool = False

    def to_dict(self, device_id: str) -> dict[str, Any]:
        return {
            "kind": "gas",
            "device_id": device_id,
            "active": self.active,
            "since": self.since,
            "gas_adc": self.gas_adc,
            "raised_by": [n for n, f in (("device", self.device_flag), ("backend", self.backend_flag)) if f],
        }


class GasMonitor:
    def __init__(self, warning_adc: int, clear_adc: int):
        self.warning_adc = warning_adc
        self.clear_adc = clear_adc
        self._states: dict[str, GasState] = {}
        self._lock = threading.Lock()

    def update(self, device_id: str, gas_adc: Optional[int], device_flag: bool) -> Optional[dict[str, Any]]:
        with self._lock:
            st = self._states.setdefault(device_id, GasState())
            was_active = st.active

            if gas_adc is not None:
                st.gas_adc = gas_adc
                if gas_adc >= self.warning_adc:
                    st.backend_flag = True
                elif gas_adc <= self.clear_adc:
                    st.backend_flag = False

            st.device_flag = device_flag
            st.active = st.backend_flag or st.device_flag

            if st.active and not was_active:
                st.since = to_iso(utc_now())
            elif not st.active:
                st.since = None

            if st.active != was_active:
                return st.to_dict(device_id)
            return None

    def is_active(self, device_id: str) -> bool:
        with self._lock:
            st = self._states.get(device_id)
            return bool(st and st.active)

    def any_active(self) -> bool:
        with self._lock:
            return any(s.active for s in self._states.values())

    def warnings(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.to_dict(d) for d, s in self._states.items() if s.active]


def check_command(
    target: str,
    state: str,
    source: str,
    gas_active: bool,
    acknowledged_gas_warning: bool = False,
) -> Optional[str]:
    if source in {"rule", "ml"}:
        if target == "buzzer":
            return "Automation may not operate the buzzer"
        if gas_active and target == "fan" and state == "on":
            return "Automatic fan start is blocked during a gas warning"
    if source == "user" and gas_active and target == "fan" and state == "on" and not acknowledged_gas_warning:
        return "Gas warning active: confirm that starting the fan is safe in this environment"
    return None
