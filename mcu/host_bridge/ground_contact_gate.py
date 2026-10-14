from __future__ import annotations

import dataclasses
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine.auth import sign_command  # noqa: E402
from sim.driver import _epoch_datetime  # noqa: E402
from sim.orbit import Pass, find_passes, load_satellite  # noqa: E402
from sim.scenario import GROUND_STATIONS_DUAL  # noqa: E402

from mcu.host_bridge.uart_bridge import (  # noqa: E402
    Decision,
    ResponseLine,
    UartBridge,
)

def compute_contact_windows(
    *,
    duration_s: float,
    min_elevation_deg: float,
    stations: Sequence[tuple[float, float, float]] = GROUND_STATIONS_DUAL,
    step_s: float = 10.0,
) -> tuple[list[Pass], datetime]:
    sat = load_satellite()
    epoch = _epoch_datetime(sat)
    end = epoch + timedelta(seconds=duration_s)
    passes = find_passes(
        sat, epoch, end, min_elevation_deg, step_s=step_s, stations=stations
    )
    return passes, epoch

def simulated_time_to_utc(now_s: float, epoch: datetime) -> datetime:
    return epoch + timedelta(seconds=now_s)

def in_any_window(when: datetime, windows: Sequence[Pass]) -> Optional[Pass]:
    for p in windows:
        if p.aos <= when <= p.los:
            return p
    return None

@dataclasses.dataclass(frozen=True)
class GateDecision:

    sent: bool
    now_s: float
    when_utc: datetime
    window: Optional[Pass]
    reason: str
    response: Optional[ResponseLine] = None

class GroundContactGate:

    def __init__(
        self,
        bridge: UartBridge,
        *,
        windows: Sequence[Pass],
        epoch: datetime,
        ground_auth_secret: Optional[bytes] = None,
    ) -> None:
        self._bridge = bridge
        self._windows = list(windows)
        self._epoch = epoch
        self._ground_auth_secret = ground_auth_secret

    def send_gated_inject(
        self,
        event_id: str,
        state_id: str,
        now_s: float,
        context: Mapping[str, Any],
        telemetry: Mapping[str, Any],
    ) -> GateDecision:
        when = simulated_time_to_utc(now_s, self._epoch)
        window = in_any_window(when, self._windows)
        if window is None:
            return GateDecision(
                sent=False,
                now_s=now_s,
                when_utc=when,
                window=None,
                reason=(
                    f"no real Phase 7B contact window covers now={now_s:.0f}s "
                    f"({when.isoformat()}) -- refusing to transmit "
                    f"{event_id!r}, nothing written to the UART"
                ),
            )

        signature = None
        if self._ground_auth_secret is not None:
            signature = sign_command(event_id, float(now_s), self._ground_auth_secret)

        self._bridge.send_inject(
            event_id, state_id, now_s, context, telemetry, signature=signature
        )
        response = self._bridge.read_response()
        return GateDecision(
            sent=True,
            now_s=now_s,
            when_utc=when,
            window=window,
            reason=(
                f"now={now_s:.0f}s ({when.isoformat()}) falls inside real "
                f"contact window [{window.aos.isoformat()}, "
                f"{window.los.isoformat()}] (max elevation "
                f"{window.max_elevation_deg:.2f} deg) -- transmitted"
            ),
            response=response,
        )
