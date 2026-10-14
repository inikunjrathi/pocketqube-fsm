# pocketqube-fsm

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23365148.svg)](https://doi.org/10.5281/zenodo.23365148)

Code, configurations and evidence for the paper *Mission-agnostic flight
software for PocketQubes: a configuration-driven, model-checked state machine
for deployment and downlink management* (Nikunj Rathi, K. J. Somaiya School of
Engineering, submitted to Acta Astronautica). Version v1.0.0, the code described in the
paper, is archived on Zenodo at https://doi.org/10.5281/zenodo.23365148.

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
tests/           1,208 tests: transitions, illegal pairs, guards, fault injection
docs/            requirements, state machines, decision records, generated results
docs/tla/        generated TLA+ specifications and TLC configurations
mcu/firmware/    C port of the engine for STM32F401RE under Zephyr
mcu/host_bridge/ UART bridge, Renode replay driver and archived equivalence logs
report/elsevier/ manuscript source and the scripts that fill its tables
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
1.16.1. `docs/phase8-c-port.md` describes the toolchain setup. The full replay
of the 48 h reference run (35,763 engine decisions, about an hour) is:

```
.venv/bin/python mcu/host_bridge/replay_baseline.py \
    --west <west> --zephyr-sdk-dir <sdk-0.17.4> --zephyr-base <zephyr-4.2.2>
```

The logs from the run reported in the paper are in
`mcu/host_bridge/evidence/task8_baseline_seed42/`. The host build of the C
authentication tests needs mbedTLS 4.x.

## Manuscript

```
cd report/elsevier
../../.venv/bin/python make_transition_tables.py
latexmk -pdf paper.tex
```

## License

MIT. See `LICENSE`. `mcu/firmware/app/src/main.c` keeps its Apache-2.0 SPDX
header.
