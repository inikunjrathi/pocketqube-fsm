from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
MCU_DIR = REPO_ROOT / "mcu"
APP_DIR = MCU_DIR / "firmware" / "app"
SRC_DIR = APP_DIR / "src"
BUILD_SCRIPT = MCU_DIR / "scripts" / "build_firmware.sh"

sys.path.insert(0, str(REPO_ROOT))

from engine.config_loader import load_config  # noqa: E402
from tools.codegen_c_table import generate_tables, render_header, render_source  # noqa: E402
from mcu.host_bridge.codegen_arbitration_table import write_arbitration_table  # noqa: E402

CONFIG_IDS = ("config-a", "config-b", "config-c")

class FirmwareBuildError(Exception):
    pass

def _write_config_table(config_id: str) -> None:
    config_path = REPO_ROOT / "config" / f"{config_id}.yaml"
    cfg = load_config(config_path)
    tables = generate_tables(cfg)
    (SRC_DIR / "engine_config_table.h").write_text(render_header(cfg, tables))
    (SRC_DIR / "engine_config_table.c").write_text(render_source(cfg, tables))
    write_arbitration_table(config_id, SRC_DIR)

def restore_committed_config_a_table() -> None:
    _write_config_table("config-a")

def build_firmware_for_config(
    config_id: str,
    *,
    west: Optional[Path] = None,
    zephyr_sdk_dir: Optional[Path] = None,
    zephyr_base: Optional[Path] = None,
    quiet: bool = True,
    build_dir_name: Optional[str] = None,
    extra_west_args: Optional[list] = None,
) -> Path:
    if config_id not in CONFIG_IDS:
        raise FirmwareBuildError(f"unknown config id {config_id!r}; expected one of {CONFIG_IDS}")

    _write_config_table(config_id)

    build_dir = APP_DIR / "build" / (build_dir_name or config_id)
    env = dict(os.environ)
    if west is not None:
        env["CEPDT_WEST"] = str(west)
    if zephyr_sdk_dir is not None:
        env["ZEPHYR_SDK_INSTALL_DIR"] = str(zephyr_sdk_dir)
    if zephyr_base is not None:
        env["ZEPHYR_BASE"] = str(zephyr_base)
    env["CEPDT_BUILD_DIR"] = str(build_dir)

    result = subprocess.run(
        [str(BUILD_SCRIPT), *(extra_west_args or [])],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FirmwareBuildError(
            f"mcu/scripts/build_firmware.sh failed for {config_id} "
            f"(exit {result.returncode}):\n--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    if not quiet:
        print(result.stdout, file=sys.stderr)

    elf = build_dir / "zephyr" / "zephyr.elf"
    if not elf.exists():
        raise FirmwareBuildError(f"build reported success but no ELF found at {elf}")
    return elf
