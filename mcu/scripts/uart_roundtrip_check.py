#!/usr/bin/env python3

import os
import signal
import subprocess
import sys
import tempfile
import time

try:
    import serial
except ImportError:
    print(
        "error: pyserial not importable -- run with mcu/.venv/bin/python3, "
        "or `pip install pyserial` into the environment you're using.",
        file=sys.stderr,
    )
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MCU_DIR = os.path.dirname(SCRIPT_DIR)
RUN_RENODE = os.path.join(SCRIPT_DIR, "run_renode.sh")

UART_PTY = "/tmp/cepdt_nucleo_f401re_uart_roundtrip_test"

BAUD_RATE = 115200
BOOT_TIMEOUT_S = 30.0
BOOT_POLL_INTERVAL_S = 0.2
SERIAL_TIMEOUT_S = 3.0

TEST_CASES = [
    b"A",
    b"Hello, Renode!",
    b"INJECT EVT_X S1 100 ctx k=v ; tlm a=1\n",
    bytes(range(1, 128)),
]

def wait_for_pty(path, timeout_s, poll_interval_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if os.path.islink(path) or os.path.exists(path):
            return True
        time.sleep(poll_interval_s)
    return False

def run_roundtrip(pty_path):
    ser = serial.Serial(pty_path, BAUD_RATE, timeout=SERIAL_TIMEOUT_S)
    try:
        time.sleep(0.3)

        failures = []
        for i, payload in enumerate(TEST_CASES):
            ser.reset_input_buffer()
            ser.write(payload)
            ser.flush()
            received = ser.read(len(payload))
            if received != payload:
                failures.append(
                    "case %d: sent %r, received %r" % (i, payload, received)
                )
            else:
                print("PASS case %d: %d bytes echoed correctly" % (i, len(payload)))
        return failures
    finally:
        ser.close()

def main():
    if os.path.islink(UART_PTY) or os.path.exists(UART_PTY):
        os.remove(UART_PTY)

    env = dict(os.environ)
    env["CEPDT_UART_PTY"] = UART_PTY

    log_fd, log_path = tempfile.mkstemp(prefix="cepdt_renode_", suffix=".log")
    os.close(log_fd)

    print("cepdt/mcu: launching Renode via %s (log: %s)" % (RUN_RENODE, log_path), file=sys.stderr)
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [RUN_RENODE],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        try:
            if not wait_for_pty(UART_PTY, BOOT_TIMEOUT_S, BOOT_POLL_INTERVAL_S):
                print(
                    "FAIL: Renode did not expose the UART pty within %.0fs"
                    % BOOT_TIMEOUT_S,
                    file=sys.stderr,
                )
                _dump_log(log_path)
                return 1

            if proc.poll() is not None:
                print(
                    "FAIL: Renode subprocess exited early (code %s) before the "
                    "round trip could run" % proc.returncode,
                    file=sys.stderr,
                )
                _dump_log(log_path)
                return 1

            try:
                failures = run_roundtrip(UART_PTY)
            except Exception as exc:  # noqa: BLE001 -- report and fail cleanly
                print("FAIL: exception during round trip: %r" % exc, file=sys.stderr)
                _dump_log(log_path)
                return 1

            if failures:
                print("FAIL: %d round-trip case(s) mismatched:" % len(failures), file=sys.stderr)
                for f in failures:
                    print("  - %s" % f, file=sys.stderr)
                _dump_log(log_path)
                return 1

            print(
                "PASS: all %d round-trip case(s) echoed correctly, zero manual "
                "Renode-monitor steps." % len(TEST_CASES)
            )
            return 0
        finally:
            _terminate_group(proc)
            if os.path.islink(UART_PTY) or os.path.exists(UART_PTY):
                try:
                    os.remove(UART_PTY)
                except OSError:
                    pass
            try:
                os.remove(log_path)
            except OSError:
                pass

def _terminate_group(proc):
    if proc.poll() is not None:
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

def _dump_log(log_path):
    print("--- Renode subprocess log (%s) ---" % log_path, file=sys.stderr)
    try:
        with open(log_path) as f:
            sys.stderr.write(f.read())
    except OSError as exc:
        print("(could not read log: %r)" % exc, file=sys.stderr)

if __name__ == "__main__":
    sys.exit(main())
