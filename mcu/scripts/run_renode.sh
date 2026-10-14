#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCU_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ELF="${CEPDT_FIRMWARE_ELF:-${MCU_DIR}/firmware/app/build/zephyr/zephyr.elf}"
UART_PTY="${CEPDT_UART_PTY:-/tmp/cepdt_nucleo_f401re_uart}"
MONITOR_PORT="${CEPDT_RENODE_MONITOR_PORT:-0}"
RESC="${MCU_DIR}/renode/nucleo_f401re.resc"

if [[ ! -f "${ELF}" ]]; then
    echo "error: firmware ELF not found: ${ELF}" >&2
    echo "       build it first: ${SCRIPT_DIR}/build_firmware.sh" >&2
    exit 1
fi

if [[ ! -f "${RESC}" ]]; then
    echo "error: Renode script not found: ${RESC}" >&2
    exit 1
fi

if ! command -v renode >/dev/null 2>&1; then
    echo "error: 'renode' not found on PATH (expected Renode 1.16.1)" >&2
    exit 1
fi

echo "cepdt/mcu: booting ${ELF}" >&2
echo "cepdt/mcu: UART pty will appear at ${UART_PTY}" >&2

exec renode --disable-xwt -P "${MONITOR_PORT}" \
    -e "\$bin=@${ELF}; \$uart_pty=\"${UART_PTY}\"; include @${RESC}"
