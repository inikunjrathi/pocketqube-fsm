#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCU_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${MCU_DIR}/firmware/app"
BUILD_DIR="${CEPDT_BUILD_DIR:-${APP_DIR}/build}"

WEST="${CEPDT_WEST:-${MCU_DIR}/.venv/bin/west}"
export ZEPHYR_BASE="${ZEPHYR_BASE:-${HOME}/zephyrproject/zephyr}"
export ZEPHYR_SDK_INSTALL_DIR="${ZEPHYR_SDK_INSTALL_DIR:-${MCU_DIR}/.toolchains/zephyr-sdk-0.17.4}"
export ZEPHYR_TOOLCHAIN_VARIANT="${ZEPHYR_TOOLCHAIN_VARIANT:-zephyr}"

if [[ ! -x "${WEST}" ]]; then
    echo "error: west not found at ${WEST}" >&2
    echo "       (expected the mcu/.venv Python venv with west==1.5.0 installed)" >&2
    exit 1
fi

if [[ ! -d "${ZEPHYR_BASE}" ]]; then
    echo "error: ZEPHYR_BASE not found: ${ZEPHYR_BASE}" >&2
    echo "       (expected the West workspace's zephyr/ checkout, tag v4.2.2)" >&2
    exit 1
fi

if [[ ! -x "${ZEPHYR_SDK_INSTALL_DIR}/arm-zephyr-eabi/bin/arm-zephyr-eabi-gcc" ]]; then
    echo "error: arm-zephyr-eabi-gcc not found under ${ZEPHYR_SDK_INSTALL_DIR}" >&2
    echo "       see the toolchain setup in docs/phase8-c-port.md." >&2
    exit 1
fi

echo "cepdt/mcu: ZEPHYR_BASE=${ZEPHYR_BASE}" >&2
echo "cepdt/mcu: ZEPHYR_SDK_INSTALL_DIR=${ZEPHYR_SDK_INSTALL_DIR}" >&2
echo "cepdt/mcu: building ${APP_DIR} -> ${BUILD_DIR} (board: nucleo_f401re)" >&2

"${WEST}" build -b nucleo_f401re -d "${BUILD_DIR}" "${APP_DIR}" --pristine "$@"

echo "cepdt/mcu: build OK -> ${BUILD_DIR}/zephyr/zephyr.elf" >&2
