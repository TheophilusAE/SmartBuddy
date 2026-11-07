from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .. import device_gateway as gw
from ..context import AppContext
from ..device_gateway import DeviceIdentity
from ..safety import check_command
from ..schemas import OperatingMode, ReadingIn
from .readings_service import StoreResult, record_rejection, store_reading

log = logging.getLogger(__name__)


def ingest_reading(ctx: AppContext, reading: ReadingIn, identity: DeviceIdentity, received: datetime) -> StoreResult:
    with ctx.db.transaction() as conn:
        result = store_reading(conn, reading, identity.simulated, received, ctx.settings.clock_skew_s)
        if result.status == "duplicate":
            record_rejection(conn, "duplicate", identity.device_id, received)
            return result
        mode = ctx.get_mode(conn)

    row = result.row
    assert row is not None
    ctx.hub.publish("reading", row)

    warning = ctx.gas.update(identity.device_id, reading.gas_adc, reading.gas_warning_local)
    if warning:
        log.warning("gas warning %s on %s (adc=%s)", "ON" if warning["active"] else "cleared",
                    identity.device_id, reading.gas_adc)
        ctx.hub.publish("warning", warning)

    with ctx.db.transaction() as conn:
        _publish_device_state(ctx, conn, identity.device_id, received)
        if row["valid"]:
            if ctx.settings.device_control_enabled:
                _run_automation(ctx, conn, row, mode)
            ctx.ml.maybe_log_prediction(conn, row)
    return result


def _publish_device_state(ctx: AppContext, conn, device_id: str, now: datetime) -> None:
    for state in gw.device_states(conn, ctx.settings, now):
        if state["device_id"] == device_id:
            ctx.hub.publish("device_state", state)


def _run_automation(ctx: AppContext, conn, row: dict[str, Any], mode: OperatingMode) -> None:
    suggestions = None
    if mode == OperatingMode.ML_AUTOMATIC:
        if not (ctx.settings.enable_ml_automatic and ctx.ml.model_available):
            return
        advice = ctx.ml.advise(row)
        if advice.get("basis") != "model":
            return
        suggestions = advice.get("suggested_actions") or {}

    proposals = ctx.automation.evaluate(row, mode, suggestions)
    gas_active = ctx.gas.is_active(row["device_id"])
    for p in proposals:
        blocked = check_command(p.target, p.state, p.source, gas_active)
        if blocked:
            log.info("automation %s %s=%s blocked: %s", p.source, p.target, p.state, blocked)
            continue
        event = gw.queue_command(conn, ctx.settings, row["device_id"], p.target, p.state, p.source,
                                 requested_by=None, reason=p.reason)
        ctx.automation.mark_action(row["device_id"], p.target)
        ctx.hub.publish("command_update", event)
