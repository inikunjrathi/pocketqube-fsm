# Project Plan — Configurable Scheduling Framework for PocketQube Downlink Management

**Programme:** CSBS, KJSSE
**Use case:** KJS-SRS-01 (SomaiyaSat / SomaiyaPod)
**Window:** 20 July – 25 October 2026 (14 weeks)
**Constraint:** software only. No satellite, deployer, or flight hardware access.

---

## 1. Working title

*A configurable rule-based scheduling and mode-arbitration framework for
PocketQube-class downlink management, with a learned-policy comparison.*

Scope it as a **reusable framework demonstrated on a PocketQube-class reference
configuration derived from the SomaiyaSat mission profile** — not as a
SomaiyaSat flight design. The use case document lists ICDs and mission
requirements as artifacts *still to be prepared*, so mission-specific parameter
values do not yet exist. A configurable engine is the honest response to that,
not a workaround.

## 2. Research questions

- **RQ1** — Can deployment-to-operations lifecycle management and downlink
  arbitration for a PocketQube be expressed as a mission-agnostic,
  configuration-driven state machine, and demonstrated across two structurally
  different mission configurations?
- **RQ2** — Does the framework remain in a legal state and preserve
  deployment-confirmed status across arbitrary resets, including resets during
  non-volatile writes?
- **RQ3** — Under a fixed data-class priority order (TT&C > SSTV >
  Codec2/M17), does a learned scheduling policy outperform the rule-based
  policy on delivery success, TT&C latency, and energy per delivered bit?

RQ3 is deliberately posed as a question. A negative or null result is a valid
outcome and must be reported as such.

## 3. Traceability to the use case document

| Deliverable | Document basis |
|---|---|
| Rule-based FSM fallback | Governance table, *AI Security & Trustworthiness* (High): watchdogs and fallback rule-based logic required when AI output is anomalous |
| Safe-mode / override model | Governance table, *Human-in-the-Loop*: ground operators retain override; AI autonomy bounded by uplinked commands and safe-mode triggers |
| Decision rationale logging | Governance table, *Responsible AI*: logged rationale for prioritisation choices |
| Priority queue, TT&C > SSTV > voice | Solution Approach: onboard AI scheduler/router |
| Training on simulated link/power scenarios | AI Model Design & Training; Expected Outputs |
| UML state charts | CSBS Sem VI, *Software Engineering using UML* |
| Priority queue with dynamic reordering | CSBS Sem III, *Data Structures and Algorithms* |
| Lightweight decision model under power constraints | CSBS Sem III, *AI and Machine Learning* |
| Scheduling algorithm comparison | CSBS Sem IV, *Analysis of Algorithms* |
| Power–link trade-off as constrained optimisation | CSBS Sem IV, *Linear Algebra and Optimization* |
| Model compression (stretch) | CSBS Sem V, *Deep Learning & Gen AI* |

## 4. Fixed parameters taken from the document

- Data-class priority: **TT&C/housekeeping > SSTV imagery > Codec2/M17 voice/data**
- Average power budget: **sub-1W**, PocketQube-class
- Deployment confirmation mechanisms: separation switch, timer, short-duration RF beacon
- Autonomy is bounded by uplinked commands and safe-mode triggers
- Collaborating organisation: ReOrbit, Finland

Every other numeric guard value is **unspecified by the mission** and must be a
configuration parameter with a cited or explicitly-assumed justification.
Maintain a `parameters.md` table: parameter → default value → source →
confidence. This table is a graded artifact in its own right.

## 5. Architecture

### Engine (mission-agnostic — the contribution)

- Transition-table interpreter: `step(state, event, context) -> (new_state, actions)`, pure, no I/O
- Guard evaluator
- Priority-queue scheduler with dynamic reordering
- Persistence layer: A/B banks, CRC32, monotonic sequence number, one-way latch semantics
- Fault-injection harness (reset at arbitrary points, including mid-write)
- Decision logger (rationale per arbitration decision)
- Generators: UML/Graphviz state diagram, verification matrix

### Configuration (mission-specific — swappable data, YAML)

- State list, event list, transition table
- Guard parameters: timers, power thresholds, link-quality thresholds
- Data-class priority ordering
- Which flags are one-way latches
- Conflict-resolution priority ordering
- Mode exclusivity constraints

**Hard rule:** no mission-specific constant appears anywhere in engine code. If
`RF_INHIBIT` or a literal timer value appears in the engine, the split has
failed. Config is loaded externally and passed in.

### Two configurations (this is what earns the generality claim)

- **Config A — PocketQube reference.** Deployer-ejected, RF-inhibit silence
  timer, dual-path deployment confirmation, four comms modes, sub-1W budget.
- **Config B — deliberately dissimilar.** Single-path deployment switch, no RF
  inhibit, single downlink mode, ground-commanded safe-mode exit only.

If Config B forces an engine change, the engine is not general. Report that
honestly — it is a result.

## 6. Simulation environment

- **Orbit / passes:** SGP4 propagation for realistic pass geometry and duration.
  Do not use a synthetic pass-length distribution.
- **Link model:** elevation-dependent link quality with a simple fade model.
- **Power model:** illumination/eclipse cycling driving generation; per-mode
  transmit cost; battery state of charge.
- **Data generation:** stochastic arrival of TT&C, SSTV, and voice/data items
  with sizes and deadlines.

The comparison in RQ3 is only meaningful if this environment is defensible.
Budget real time for it — this is the most commonly under-built component in
projects of this shape.

## 7. Schedule

### Phase 1 — Specification (Weeks 1–2, 20 Jul – 2 Aug)

- W1: State table, event list, transition table, numbered requirements (R1..Rn) for Config A. Conflict-resolution priority ordering written explicitly and made testable — this is separate from the data-class priority the document gives you. Draft `parameters.md`.
- W2: Config schema design (what a state, event, guard, latch look like as data). Config B specification written against the schema to stress-test it. Revise schema.

**Exit criterion:** two complete configurations exist on paper, in one schema, with no engine written.

### Phase 2 — Core implementation (Weeks 3–5, 3–23 Aug)

- W3: Engine — transition interpreter, guard evaluator. Config loader. **Report writing starts this week and continues weekly.**
- W4: Persistence layer + decision logger. Priority-queue scheduler.
- W5: Diagram generator and verification-matrix generator. UML state charts produced from the transition table.

**Exit criterion:** both configs load and run; diagrams auto-generate.

### Phase 3 — Verification (Weeks 6–7, 24 Aug – 6 Sep)

- W6: Test suite — every transition-table row exercised; every illegal
  `(state, event)` pair asserted a no-op; both configs pass the same harness.
- W7: Reset fault injection at every transition boundary and mid-write. Latch
  test: no sequence of resets or corruptions may clear deployment-confirmed.
  Verification matrix generated from test results.

**Exit criterion — FREEZE.** Tag the release. RQ1 and RQ2 are answered. Do not
reopen the engine after this point except for defects.

### Phase 4 — Simulation environment (Weeks 8–9, 7–20 Sep)

- W8: SGP4 pass generation, link model, power model.
- W9: Data arrival model. Integrate rule-based policy. Establish baseline
  metrics: delivery success rate, TT&C latency distribution, energy per
  delivered bit, deadline misses by class.

**Exit criterion:** baseline results table exists. **If the schedule has slipped
by more than one week at this point, stop here and write up RQ1 + RQ2 only.**
That is a complete, defensible project.

### Phase 5 — Learned policy (Weeks 10–12, 21 Sep – 11 Oct)

- W10: Feature definition and dataset generation from the simulator. Formalise
  the power–throughput trade-off as a constrained optimisation problem (Sem IV).
- W11: Decision-tree policy. Train, evaluate against baseline on identical
  scenario seeds.
- W12: Comparison analysis. Complexity analysis of both schedulers (Sem IV).
  *Stretch only if W11 finished clean:* compressed neural policy (Sem V).

**Exit criterion:** RQ3 answered, in whichever direction.

### Phase 6 — Write-up (Weeks 13–14, 12–25 Oct)

- W13: Consolidate report. Limitations section. Migration path: which config
  fields the SomaiyaSat team would populate to adopt the framework.
- W14: Buffer, proofing, submission.

## 8. Deliverables

1. Engine source (Python, no mission constants)
2. Two configuration files, YAML
3. Auto-generated UML state charts for both configs
4. Test suite + fault-injection harness
5. Verification matrix (requirement → state/guard → test → pass/fail)
6. Simulation environment
7. Rule-based vs. learned comparison results
8. `parameters.md` — every assumed value, with source and confidence
9. Report, with a SomaiyaSat migration-path section

## 9. Explicitly out of scope

State these as scope decisions in the report, with reasons, rather than
leaving them as gaps:

- **MCU deployment and on-device power measurement.** No CSBS course maps to it,
  no hardware access, and the method (TFLite Micro on STM32 + INA-class current
  sensing) was published by Uko et al., *Discover Electronics* 3, 28 (2026).
  Discuss an FRAM-backed persistence implementation as the flight path, cited,
  not measured.
- **Onboard anomaly detection (OPSSAT-AD).** The use case places anomaly
  detection ground-side (Sem V Data Mining), not onboard. Optional extension only.
- **Flight qualification, RF implementation, deployer mechanics.** Other programmes' tracks.

## 10. Key references

- Ruszczak, Kotowski, Evans, Nalepa — *The OPS-SAT benchmark for detecting anomalies in satellite telemetry*, Scientific Data (2025), DOI 10.1038/s41597-025-05035-3. **Correction: 10.1038/s41597-025-05751-w (18 Aug 2025) — cite the corrected version.**
- Franzese, V. — *PocketQube picosatellites: survey of missions and technologies*, CEAS Space J 17, 1007–1018 (2025), DOI 10.1007/s12567-025-00603-0.
- Franzese, Kanavouras, Bruce Rosete et al. — *System design of the POQUITO PocketQube mission*, CEAS Space J 18, 97–119 (2026), DOI 10.1007/s12567-025-00624-9.
- Latachi et al. — *Reusable and Reliable Flight-Control Software for a Fail-Safe and Cost-Efficient CubeSat Mission* (Masat-1), MDPI Aerospace 7(10):146 (2020).
- *CubeSat Flight Software: Insights and a Case Study*, AIAA J. Spacecraft & Rockets, DOI 10.2514/1.A35882 — watch-point / action-point FDIR pattern.
- HERMES-TP/SP PDHU, arXiv:2101.03947 — boot/standby/safe-mode FSM topology.
- Uko, Amaizu, Ekpo et al. — *Energy-aware dynamic programming scheduler for TinyML workloads on energy-harvesting CubeSat-IoT platforms*, Discover Electronics 3, 28 (2026), DOI 10.1007/s44291-026-00179-x.
- *TinyML Enhances CubeSat Mission Capabilities*, ICCPS 2026, arXiv:2603.20174.
- NASA NEPP — *State of Memory Pattern Assessment* (2021); JPL MNOS EEPROM in-flight experience report — persistence and redundancy justification.

## 11. Open items to resolve in Week 1

1. Is this assessed as one course's project or a cross-course capstone? Changes whether Phase 5 is centrepiece or stretch.
2. Which semester you are in — determines whether Sem V/VI rows are claimable.
3. Whether the SomaiyaSat team has any draft ICD, even partial. If one appears mid-project, it becomes Config A's parameter source rather than your assumptions.
4. Confirm the submission date.

## 12. Note for the report

The use case document is titled "…Autonomous AI-Based **Inter-Satellite** Data
Routing," but its body describes only satellite-to-ground routing; no second
spacecraft appears anywhere in the document. Flag this discrepancy and state
which interpretation you built against.
