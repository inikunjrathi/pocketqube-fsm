# Research Papers

Source list of every research paper / technical report referenced by this project,
compiled from ["Key references"](../somaiyasat_csbs_project_plan.md#10-key-references)
in `somaiyasat_csbs_project_plan.md` (the only section citing external literature;
all other in-repo "reference" mentions are cross-references between project docs,
not external citations).

Full-text PDFs are downloaded into [`papers/`](../papers/) (git-ignored — see
`.gitignore`). Filenames are numbered to match the order below.

| # | Citation | Link | Downloaded |
|---|----------|------|------------|
| 1 | Ruszczak, Kotowski, Evans, Nalepa — *The OPS-SAT benchmark for detecting anomalies in satellite telemetry*, Scientific Data (2025). **Corrected DOI (18 Aug 2025) — use this one, not the original 10.1038/s41597-025-05035-3.** | [doi.org/10.1038/s41597-025-05751-w](https://doi.org/10.1038/s41597-025-05751-w) | ✅ `papers/01-ops-sat-benchmark-sci-data-2025.pdf` |
| 2 | Franzese, V. — *PocketQube picosatellites: survey of missions and technologies*, CEAS Space J 17, 1007–1018 (2025) | [doi.org/10.1007/s12567-025-00603-0](https://doi.org/10.1007/s12567-025-00603-0) | ❌ Not downloaded — Springer paywall (redirects to a login/cookie-gate page instead of serving the PDF; no open-access route found). |
| 3 | Franzese, Kanavouras, Bruce Rosete et al. — *System design of the POQUITO PocketQube mission*, CEAS Space J 18, 97–119 (2026) | [doi.org/10.1007/s12567-025-00624-9](https://doi.org/10.1007/s12567-025-00624-9) | ❌ Not downloaded — Springer paywall (same as above). |
| 4 | Latachi et al. — *Reusable and Reliable Flight-Control Software for a Fail-Safe and Cost-Efficient CubeSat Mission* (Masat-1), MDPI Aerospace 7(10):146 (2020) | [doi.org/10.3390/aerospace7100146](https://doi.org/10.3390/aerospace7100146) | ❌ Not downloaded — MDPI's Akamai bot-protection returned 403/Access Denied to automated fetches; open access, but needs a manual browser download. |
| 5 | *CubeSat Flight Software: Insights and a Case Study*, AIAA J. Spacecraft & Rockets — watch-point / action-point FDIR pattern | [doi.org/10.2514/1.A35882](https://doi.org/10.2514/1.A35882) | ❌ Not downloaded — AIAA ARC paywall (403 on direct fetch). |
| 6 | HERMES-TP/SP PDHU — boot/standby/safe-mode FSM topology | [arxiv.org/abs/2101.03947](https://arxiv.org/abs/2101.03947) | ✅ `papers/06-hermes-tp-sp-pdhu-arxiv-2101.03947.pdf` |
| 7 | Uko, Amaizu, Ekpo et al. — *Energy-aware dynamic programming scheduler for TinyML workloads on energy-harvesting CubeSat-IoT platforms*, Discover Electronics 3, 28 (2026) | [doi.org/10.1007/s44291-026-00179-x](https://doi.org/10.1007/s44291-026-00179-x) | ✅ `papers/07-uko-tinyml-scheduler-2026.pdf` |
| 8 | *TinyML Enhances CubeSat Mission Capabilities*, ICCPS 2026 | [arxiv.org/abs/2603.20174](https://arxiv.org/abs/2603.20174) | ✅ `papers/08-tinyml-cubesat-iccps2026-arxiv-2603.20174.pdf` |
| 9 | NASA NEPP — *State of Memory Pattern Assessment* (2021) — persistence and redundancy justification | [nepp.nasa.gov/docs/papers/2021-Murphy-Memory-Pattern-Assessment-Report-CL-22-1768.pdf](https://nepp.nasa.gov/docs/papers/2021-Murphy-Memory-Pattern-Assessment-Report-CL-22-1768.pdf) | ✅ `papers/09-nasa-nepp-memory-pattern-assessment-2021.pdf` |
| 10 | JPL MNOS EEPROM in-flight experience report — persistence and redundancy justification | [nepp.nasa.gov/files/16152/05_001 Chen EEPROM Final Report.pdf](https://nepp.nasa.gov/files/16152/05_001%20Chen%20%20EEPROM%20Final%20Report.pdf) | ✅ `papers/10-jpl-mnos-eeprom-chen-final-report.pdf` |

## Notes

- Rows 9 and 10 come from a single bullet in the project plan ("NASA NEPP ... ; JPL MNOS EEPROM ...") that cites two separate reports; neither had a DOI in the source, so both were located by web search and are cited by direct URL instead.
- For the four papers that couldn't be auto-downloaded (rows 2, 3, 4, 5), use the DOI link to open the publisher page in a browser and download manually (institutional access may be required for rows 2, 3, and 5). Rows 4 and 5, plus the OPS-SAT paper (row 1, original pre-correction DOI), were subsequently downloaded manually and added to `papers/` under their raw publisher filenames (`aerospace-07-00146-with-cover.pdf`, `cubesat-flight-software-insights-and-a-case-study.pdf`, `s41597-025-05035-3.pdf`).

## Selected for the PROJECT PROPOSAL Google Doc

The Google Doc's own literature review (Papers 1-3, filled in by a teammate) is about
AI-augmented satellite link-budget calculation and GEO/multibeam traffic simulation —
a different sub-topic from this repo's own CubeSat FSM/fault-injection focus. Per the
user, Papers 1-3 are placeholders that will be replaced later, so the two papers
inserted into slots **4.4 Paper 4** and **4.5 Paper 5** were instead chosen as the two
most *core* to this repo's actual project (CubeSat FSM verification with fault
injection and persistence testing), independent of what Papers 1-3 already say:

- **4.4 Paper 4** — Row 6, HERMES-TP/SP PDHU (Guzman et al., 2021): the boot/standby/safe-mode FSM topology directly maps onto this project's own state machine and fault-injection test design.
- **4.5 Paper 5** — Row 9, NASA NEPP State of Memory Pattern Assessment (Murphy et al., 2021/2022): its fault taxonomy and finding that common memory-test patterns under-cover coupling/state-dependent faults directly motivates this repo's latch-survival-across-RESET and memory-bank-selection fuzz testing.
