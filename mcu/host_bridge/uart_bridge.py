from __future__ import annotations

import dataclasses
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Union

try:
    import serial
except ImportError:  # pragma: no cover -- see module-level usage docstring
    print(
        "error: pyserial not importable -- run with mcu/.venv/bin/python3, "
        "or `pip install pyserial` into the environment you're using.",
        file=sys.stderr,
    )
    raise

MCU_DIR = Path(__file__).resolve().parents[1]
RUN_RENODE = MCU_DIR / "scripts" / "run_renode.sh"

DEFAULT_BAUD_RATE = 115200
DEFAULT_BOOT_TIMEOUT_S = 30.0
DEFAULT_BOOT_POLL_INTERVAL_S = 0.2
DEFAULT_READ_TIMEOUT_S = 5.0

class UartBridgeError(Exception):
    pass

class RenodeSession:

    def __init__(
        self,
        elf_path: Path,
        *,
        uart_pty: str,
        monitor_port: int = 0,
        boot_timeout_s: float = DEFAULT_BOOT_TIMEOUT_S,
        boot_poll_interval_s: float = DEFAULT_BOOT_POLL_INTERVAL_S,
        log_path: Optional[Path] = None,
    ) -> None:
        self.elf_path = Path(elf_path)
        self.uart_pty = uart_pty
        self.monitor_port = monitor_port
        self.boot_timeout_s = boot_timeout_s
        self.boot_poll_interval_s = boot_poll_interval_s
        self.log_path = log_path
        self._proc: Optional[subprocess.Popen] = None
        self._log_file = None

    def __enter__(self) -> "RenodeSession":
        if os.path.islink(self.uart_pty) or os.path.exists(self.uart_pty):
            os.remove(self.uart_pty)

        env = dict(os.environ)
        env["CEPDT_FIRMWARE_ELF"] = str(self.elf_path)
        env["CEPDT_UART_PTY"] = self.uart_pty
        env["CEPDT_RENODE_MONITOR_PORT"] = str(self.monitor_port)

        if self.log_path is not None:
            self._log_file = open(self.log_path, "w")
            stdout_target = self._log_file
        else:
            stdout_target = subprocess.DEVNULL

        self._proc = subprocess.Popen(
            [str(RUN_RENODE)],
            env=env,
            stdout=stdout_target,
            stderr=subprocess.STDOUT if self.log_path is not None else subprocess.DEVNULL,
            start_new_session=True,
        )

        if not self._wait_for_pty():
            self._terminate_group()
            raise UartBridgeError(
                f"Renode did not expose the UART pty ({self.uart_pty}) within "
                f"{self.boot_timeout_s:.0f}s"
                + (f" -- see log: {self.log_path}" if self.log_path else "")
            )
        if self._proc.poll() is not None:
            raise UartBridgeError(
                f"Renode subprocess exited early (code {self._proc.returncode}) "
                "before the UART pty could be used"
                + (f" -- see log: {self.log_path}" if self.log_path else "")
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._terminate_group()
        if os.path.islink(self.uart_pty) or os.path.exists(self.uart_pty):
            try:
                os.remove(self.uart_pty)
            except OSError:
                pass
        if self._log_file is not None:
            self._log_file.close()

    def _wait_for_pty(self) -> bool:
        deadline = time.monotonic() + self.boot_timeout_s
        while time.monotonic() < deadline:
            if os.path.islink(self.uart_pty) or os.path.exists(self.uart_pty):
                return True
            time.sleep(self.boot_poll_interval_s)
        return False

    def _terminate_group(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

def format_wire_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)

def format_inject_line(
    event_id: str,
    state_id: str,
    now: float,
    context: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    *,
    signature: Optional[str] = None,
) -> str:
    parts = ["INJECT", event_id, state_id, format_wire_value(now)]
    for k, v in context.items():
        parts.append(f"{k}={format_wire_value(v)}")
    parts.append(";")
    for k, v in telemetry.items():
        parts.append(f"{k}={format_wire_value(v)}")
    if signature is not None:
        parts.append("SIG")
        parts.append(signature)
    return " ".join(parts)

@dataclasses.dataclass(frozen=True)
class Ready:
    pass

@dataclasses.dataclass(frozen=True)
class Decision:

    now: float
    from_state: str
    event_id: str
    to_state: str
    transition_id: Optional[str]
    legal: bool
    actions: tuple[str, ...]

    def as_comparison_tuple(self) -> tuple[str, Optional[str], tuple[str, ...], bool]:
        return (self.to_state, self.transition_id, self.actions, self.legal)

@dataclasses.dataclass(frozen=True)
class Error:

    reason: str
    detail: Optional[str]

@dataclasses.dataclass(frozen=True)
class Raw:

    text: str

ResponseLine = Union[Ready, Decision, Error, Raw]

def parse_response_line(line: str) -> ResponseLine:
    line = line.rstrip("\r\n")
    if line == "READY":
        return Ready()
    if line.startswith("ERROR"):
        rest = line[len("ERROR"):].strip()
        if not rest:
            return Error(reason="(empty)", detail=None)
        parts = rest.split(" ", 1)
        return Error(reason=parts[0], detail=parts[1] if len(parts) > 1 else None)
    if line.startswith("DECISION"):
        return _parse_decision_line(line)
    return Raw(text=line)

def _split_first_token(s: str) -> tuple[str, str]:
    idx = s.find(" ")
    if idx == -1:
        return s, ""
    return s[:idx], s[idx + 1:]

def _parse_decision_line(line: str) -> Decision:
    prefix = "DECISION "
    if not line.startswith(prefix):
        raise UartBridgeError(f"malformed DECISION line (missing prefix): {line!r}")
    rest = line[len(prefix):]

    now_tok, rest = _split_first_token(rest)
    from_state, rest = _split_first_token(rest)
    event_id, rest = _split_first_token(rest)
    arrow_tok, rest = _split_first_token(rest)
    to_state, rest = _split_first_token(rest)
    if arrow_tok != "->":
        raise UartBridgeError(f"malformed DECISION line (expected '->'): {line!r}")

    if not rest.startswith("transition="):
        raise UartBridgeError(f"malformed DECISION line (expected 'transition='): {line!r}")
    rest = rest[len("transition="):]
    transition_tok, rest = _split_first_token(rest)

    if not rest.startswith("legal="):
        raise UartBridgeError(f"malformed DECISION line (expected 'legal='): {line!r}")
    rest = rest[len("legal="):]
    legal_tok, rest = _split_first_token(rest)

    if not rest.startswith("actions="):
        raise UartBridgeError(f"malformed DECISION line (expected 'actions='): {line!r}")
    actions_value = rest[len("actions="):]

    now = float(now_tok)
    transition_id = None if transition_tok == "NONE" else transition_tok
    legal = legal_tok == "1"
    actions = () if actions_value == "NONE" else tuple(actions_value.split(","))
    return Decision(
        now=now,
        from_state=from_state,
        event_id=event_id,
        to_state=to_state,
        transition_id=transition_id,
        legal=legal,
        actions=actions,
    )

class UartBridge:
    def __init__(self, port: str, *, baud_rate: int = DEFAULT_BAUD_RATE, timeout_s: float = DEFAULT_READ_TIMEOUT_S) -> None:
        self._ser = serial.Serial(port, baud_rate, timeout=timeout_s)
        self._recv_buf = b""

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "UartBridge":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def wait_for_ready(self, timeout_s: float = DEFAULT_READ_TIMEOUT_S) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            line = self._read_line(timeout_s=remaining)
            if line is None:
                continue
            parsed = parse_response_line(line)
            if isinstance(parsed, Ready):
                return
        raise UartBridgeError(f"no READY line received within {timeout_s:.0f}s")

    def send_inject(
        self,
        event_id: str,
        state_id: str,
        now: float,
        context: Mapping[str, Any],
        telemetry: Mapping[str, Any],
        *,
        signature: Optional[str] = None,
    ) -> None:
        line = format_inject_line(event_id, state_id, now, context, telemetry, signature=signature)
        self._ser.write((line + "\n").encode("ascii"))
        self._ser.flush()

    def read_response(self, timeout_s: float = DEFAULT_READ_TIMEOUT_S) -> ResponseLine:
        line = self._read_line(timeout_s=timeout_s)
        if line is None:
            raise UartBridgeError(f"no response line received within {timeout_s:.0f}s")
        return parse_response_line(line)

    def _read_line(self, *, timeout_s: float) -> Optional[str]:
        deadline = time.monotonic() + timeout_s
        while b"\n" not in self._recv_buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._ser.timeout = remaining
            chunk = self._ser.read(1)
            if not chunk:
                return None
            self._recv_buf += chunk
        line, _, self._recv_buf = self._recv_buf.partition(b"\n")
        return line.decode("ascii", errors="replace")
