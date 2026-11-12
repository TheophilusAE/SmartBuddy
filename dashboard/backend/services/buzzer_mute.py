from __future__ import annotations

import math
import threading
from typing import Optional

from ..database import get_setting, set_setting
from ..timeutil import to_iso, utc_now

MUTE_S = 300
KEY = "buzzer_mute_until:{}"


# silences the gas buzzer for one alarm, at most MUTE_S; the alarm itself stays active
class BuzzerMute:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str, int] = {}

    def _get(self, conn, device_id: str) -> int:
        if device_id not in self._until:
            raw = get_setting(conn, KEY.format(device_id))
            self._until[device_id] = int(raw) if raw and raw.isdigit() else 0
        return self._until[device_id]

    def _set(self, conn, device_id: str, until_ms: int, by: Optional[str]) -> None:
        set_setting(conn, KEY.format(device_id), str(until_ms), to_iso(utc_now()), by)
        self._until[device_id] = until_ms

    def silence(self, conn, device_id: str, now_ms: int, by: str) -> int:
        with self._lock:
            until = now_ms + MUTE_S * 1000
            self._set(conn, device_id, until, by)
            return until

    def cancel(self, conn, device_id: str, by: str) -> None:
        with self._lock:
            self._set(conn, device_id, 0, by)

    def until(self, conn, device_id: str, now_ms: int) -> Optional[int]:
        with self._lock:
            u = self._get(conn, device_id)
            return u if u > now_ms else None

    def remaining_s(self, conn, device_id: str, alarm_active: bool, now_ms: int) -> int:
        with self._lock:
            u = self._get(conn, device_id)
            if not u:
                return 0
            # the mute belongs to one alarm: once it clears, the next alarm beeps again
            if not alarm_active or u <= now_ms:
                self._set(conn, device_id, 0, "device")
                return 0
            return math.ceil((u - now_ms) / 1000)
