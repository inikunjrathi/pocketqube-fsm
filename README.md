# pocketqube-fsm

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23365147.svg)](https://doi.org/10.5281/zenodo.23365147)

Code, configurations and evidence for the paper *Configuration-driven mode
logic for resource-constrained embedded systems: requirement-based model
checking, torn-write persistence and a PocketQube case study* (Nikunj Rathi,
Purva Pote and Megha Sharma, K. J. Somaiya School of Engineering), prepared for
the Journal of Systems Architecture. Every release is archived on
Zenodo; https://doi.org/10.5281/zenodo.23365147 resolves to the latest one.

The engine holds no mission constants. Lifecycle states, events, guarded
transitions, persisted latches, downlink priorities and event-conflict ranks
live in YAML files checked against one schema, and the same engine runs three
structurally different configurations without code changes:

| Config | States | Deployment confirmation | Safe-mode exit |
|---|---|---|---|
| `config/config-a.yaml` | 10 | separation switch + timer, and RF beacon | autonomous or ground |
| `config/config-b.yaml` | 7 | switch + debounce | ground only |
| `config/config-c.yaml` | 7 | switch + debounce | autonomous or ground |

Config A is a reference configuration derived from the SomaiyaSat PocketQube
use case. The simulation uses the published orbit, battery, solar and link
figures of the POQUITO PocketQube (NORAD 98706).

## Layout

```
config/          mission configurations (YAML)
engine/          state machine, guards, scheduler, arbitration, persistence, auth
sim/             SGP4 orbit, link, power and data-arrival models; simulation driver
policy/          rule-based, lookahead, decision-tree and clairvoyant-bound policies
tools/           generators for every results table, TLA+ specs and C tables
tests/           1,218 tests: transitions, illegal pairs, guards, fault injection
docs/            requirements, state machines, decision records, generated results
docs/tla/        TLA+ specifications: generated per config, hand-written two-bank model
mcu/firmware/    C port of the engine for STM32F401RE and STM32L476RG under Zephyr
mcu/host_bridge/ UART bridge, Renode replay and measurement drivers, archived logs
report/jsa/      current manuscript source
report/elsevier/ earlier manuscript and the scripts that fill its tables
```

## Running it

Tested with Python 3.14:

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Each results table in the paper comes from one generator. They write into
`docs/`:

```
.venv/bin/python tools/generate_baseline_results.py
.venv/bin/python tools/generate_policy_comparison.py        # about 20 min on 30 cores
.venv/bin/python tools/generate_sensitivity_analysis.py
.venv/bin/python tools/generate_ground_station_analysis.py
.venv/bin/python tools/generate_worst_case_scenarios.py
```

Model checking needs Java and the TLA+ tools jar:

```
mkdir -p tools/vendor
curl -sL -o tools/vendor/tla2tools.jar \
    https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar
bash tools/run_model_check.sh
```

## C port and emulated hardware

The firmware builds with Zephyr 4.2.2 and Zephyr SDK 0.17.4 and runs on Renode
1.17.0. `docs/phase8-c-port.md` describes the toolchain setup. The full replay
of the 48 h reference run (35,763 engine decisions, about 40 minutes) is:

```
.venv/bin/python mcu/host_bridge/replay_baseline.py \
    --west <west> --zephyr-sdk-dir <sdk-0.17.4> --zephyr-base <zephyr-4.2.2>
```

Add `--config config-b` or `--config config-c` for the other configurations.
`mcu/host_bridge/measure_firmware.py --config <config>` counts flash writes and
instructions and reports stack use and image size; it needs `CEPDT_WEST` and
`ZEPHYR_SDK_INSTALL_DIR` set. Set `CEPDT_BOARD=nucleo_l476rg` to target the
L476RG, which runs on the same emulator; neither board has been run on hardware.

The logs from the runs reported in the paper are in
`mcu/host_bridge/evidence/task8_baseline_seed42/`, and the measurements are in
`mcu/host_bridge/evidence/measurements/`. The host build of the C
authentication tests needs mbedTLS 4.x.

## Manuscript

```
cd report/jsa
latexmk -pdf paper.tex
```

## License

MIT. See `LICENSE`. `mcu/firmware/app/src/main.c` keeps its Apache-2.0 SPDX
header.
