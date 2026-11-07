from __future__ import annotations

from typing import Any, Optional

from .common import COMFORT_SCALE

GENERAL_TEMP = (20.0, 26.0)
GENERAL_HUMIDITY = (30.0, 60.0)
GENERAL_LIGHT_MIN_PCT = 30.0


def label_for(score: float) -> str:
    return COMFORT_SCALE[int(min(5, max(1, round(score))))]


def recommend(conditions: dict[str, Any], estimate: Optional[float]) -> dict[str, Any]:
    temp = conditions.get("temperature_c")
    hum = conditions.get("humidity_pct")
    light = conditions.get("light_pct")
    motion = conditions.get("motion_detected")
    fan_on = (conditions.get("actuators") or {}).get("fan")
    light_on = (conditions.get("actuators") or {}).get("light")

    tips: list[str] = []
    actions: dict[str, str] = {}

    if temp is not None and temp > GENERAL_TEMP[1]:
        tips.append(f"It's {temp:.1f} °C, warmer than the usual indoor range. Turning on the fan may help it feel cooler.")
        if not fan_on:
            actions["fan"] = "on"
    elif temp is not None and temp < GENERAL_TEMP[0]:
        tips.append(f"It's {temp:.1f} °C, cooler than the usual indoor range.")
        if fan_on:
            tips.append("The fan is on; switching it off may feel warmer.")
            actions["fan"] = "off"

    if hum is not None and hum > GENERAL_HUMIDITY[1]:
        tips.append(f"Humidity is {hum:.0f} %, on the high side. Some airflow may make it feel less stuffy.")
    elif hum is not None and hum < GENERAL_HUMIDITY[0]:
        tips.append(f"Humidity is {hum:.0f} %, on the dry side.")

    if light is not None and light < GENERAL_LIGHT_MIN_PCT and motion:
        tips.append(f"It's fairly dim ({light:.0f} % light level) and there's movement. More light may be more comfortable.")
        if not light_on:
            actions["light"] = "on"

    if not tips:
        tips.append("Conditions are within the usual indoor ranges.")

    if estimate is None:
        headline = "No personal comfort model yet - showing general guidance only."
        basis = "general"
    else:
        headline = f"Estimated comfort {estimate:.1f} / 5 ({label_for(estimate).lower()})."
        basis = "model"
        if estimate >= 4:
            actions = {}

    return {
        "basis": basis,
        "headline": headline,
        "tips": tips,
        "suggested_actions": actions,
        "disclaimer": (
            "Suggestions are based on your own past ratings (if a model exists) and simple rules of thumb. "
            "They are not medical or scientific advice."
        ),
    }
