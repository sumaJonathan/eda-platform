# Unified EDA Platform — Build Roadmap

> A personal project to build a single platform that meshes analog simulation (LTspice),
> digital simulation (Logisim), PCB design (KiCad/Eagle), and custom IC layout (Cadence)
> on one shared design database.

---

## How to use this document

- **Phases** map to GitHub **epics / milestones** (large, multi-week bodies of work).
- **Modules** map to **stories / issues** (a coherent feature, buildable in days–weeks).
- **Submodules** map to **tasks / sub-issues** (one sitting; each has a *Done when* test so you know it's finished).
- Every submodule is written to be **built and tested incrementally** — you should have something runnable at the end of each one.
- Timelines are **rough, solo, part-time** estimates for planning only, not commitments. Learning-as-you-go time is included.

---

## Guiding principles (the architecture in one screen)

1. **One design, many views.** A component (a *cell*) has several representations (*views*): a symbol, a SPICE model, a footprint, a physical layout. Every tool in the platform is just an engine that reads/writes the view it cares about. Build this abstraction once and nothing later fights you.
2. **Shared backbone.** The connectivity graph (cells, instances, pins, nets) is common to simulation, PCB, and IC. Build it first, branch later.
3. **Prototype in Python, ship in Rust.** Prove algorithms fast in Python/NumPy with a test suite; port the hot, stabilized modules to Rust for the product, validated against the Python version as an oracle (bridge via PyO3/maturin so you never do a big-bang rewrite).
4. **Vertical slices over invisible plumbing.** Get one trivial thing working end-to-end (schematic → simulate → export) before deepening any single layer.
5. **Test against reference tools.** Regression-check every engine against an established tool (ngspice, KiCad, KLayout) and against hand-verifiable analytic answers.

---

## Tech stack decisions

| Concern | Prototype | Product core | Why |
|---|---|---|---|
| Core language | Python 3 | Rust | Python = fastest iteration; Rust = memory-safe, superb tooling for correctness-critical numeric/geometry code |
| Py↔Rust bridge | — | PyO3 + maturin | Swap in Rust modules incrementally; keep Python as oracle |
| In-memory graph | `networkx` | `petgraph` | Ready-made graph structures for the cell/instance/net model |
| Persistence | (JSON/pickle) | **own storage engine** | Learning goal + full control over format, undo, versioning |
| Serialization | json | `serde` (+ S-expr or binary) | Human-diffable text or compact binary as needed |
| Linear algebra (sim) | SciPy sparse | `faer` (Rust) or Eigen + **KLU** (C++) | KLU is purpose-built for circuit-simulation matrices |
| Reference SPICE | `ahkab`, PySpice/ngspice | ngspice / Xyce (embed/compare) | ahkab = readable learning ref; ngspice = regression oracle |
| Geometry (PCB/IC) | `shapely` | **Clipper2** + `rstar` (R-tree) | Clipper2 = standard polygon boolean/offset ops; R-tree = spatial index |
| GUI | **PySide6 (Qt)** | egui **or** Tauri + WebGPU | Qt `QGraphicsView` = proven infinite zoomable canvas; egui/Tauri = lightweight Rust paths |
| Digital HDL (later) | pyverilog | `sv-parser` / ANTLR | Only when text HDL import is actually needed |
| IC layout (later) | KLayout (Python API) | KLayout / Magic / OpenROAD via FFI | Integrate the mature open-silicon stack, don't reinvent |
| Layout I/O | `gdstk` | `gdstk` / gdspy | Fast, modern GDSII/OASIS read/write |
| Build + CI | — | cargo / CMake + GitHub Actions | Get CI green from module one |
| Testing | Hypothesis | `proptest` | Property-based testing is gold for solvers and geometry |

---

## Testing strategy (read first)

Every submodule's *Done when* line **is** its acceptance test — automate it in CI wherever possible. Beyond that, use a layered pyramid (bottom = most tests, run on every push; top = fewest, often manual):

1. **Unit** — pure functions: stamps, gates, geometry ops, queries. `pytest` / `cargo test`.
2. **Property / invariant** — random inputs, assert invariants always hold. `Hypothesis` / `proptest`. Best for the database (random edit sequences) and geometry.
3. **Differential (oracle)** — run two implementations that *must* agree and diff them: incremental vs brute-force, Python prototype vs Rust port, your engine vs a reference tool.
4. **Integration** — cross-module vertical slices (schematic → netlist → sim).
5. **Acceptance** — visual regression (golden images), physical (milled-board continuity), reference-tool sign-off (DRC/LVS).

**Oracles you'll lean on:** hand-derived analytic answers (circuit math); brute-force recomputation (net index); the Python prototype (for the Rust port); established tools — ngspice, Icarus Verilog / Verilator, KiCad / gerbv, KLayout / Magic / Netgen.

**Floating-point rule:** never assert exact `==` on floats — define central relative + absolute tolerances (`pytest.approx` / an `approx_eq` helper) and use them everywhere.

**Fixtures & golden files:** keep `/tests/fixtures` with reference netlists, Gerbers, VCD traces, and approved images; regenerate them deliberately and code-review every diff.

**CI gating:** unit + property + differential + regression run on every push; slow co-simulations, visual diffs, and anything physical run nightly or on demand.

**Testing tools by domain:** `pytest`/`pytest-qt` + `cargo test` (unit/interaction) · `Hypothesis`/`proptest` (property) · `Pillow` image-diff / `egui_kittest` (visual regression) · ngspice, Icarus Verilog, Verilator (engine oracles) · `gerbv`/`libgerbv`/`pcb-tools` (Gerber parse-back) · `gdstk` (GDS round-trip) · Magic, Netgen, KLayout (DRC/LVS).

---

## Phase overview

| Phase | Name | Rough effort (solo, part-time) | Depends on |
|---|---|---|---|
| 0 | Foundations & project setup | 1–2 weeks | — |
| 1 | Design database + storage engine | 8–14 weeks | 0 |
| 2 | Schematic / logic capture | 8–16 weeks | 1 |
| 3 | Analog simulator (SPICE core) | 10–20 weeks | 1 (2 helps) |
| 4 | Digital simulator | 4–8 weeks | 1 (2 helps) |
| 5 | PCB layout + fab output | 12–24 weeks | 1, 2 |
| 6 | IC / custom layout (lifetime wing) | 6+ months, open-ended | 1–5 |

**First real milestone** — a usable tool that captures a schematic, simulates it, and exports a manufacturable board — is roughly **Phases 0–3 + a slice of 5**, on the order of a year part-time. Pace it by vertical slices, not by finishing whole phases.

---

## Phase 0 — Foundations & project setup

**Overview.** Set up the repo, tooling, CI, and the project board itself. Lock the language/GUI strategy so you don't re-litigate it later. This is short but pays back every week after.

**Key concepts.** Monorepo layout; semantic versioning; CI/CD; property-based vs example-based testing; the prototype-then-port workflow.

**Tools & why.** Git + GitHub (version control + Projects board); GitHub Actions (CI from day one); Python venv/poetry (prototype env); cargo workspace (future Rust core); pre-commit hooks (format/lint).

**Resources.**
- *Pro Git* (Chaton & Straub) — free online.
- GitHub Projects docs (epics/stories/tasks).
- The Rust Book + `cargo` docs (skim now, use later).

**Modules & submodules.**
- [ ] **0.1 Repo & structure** — [ ] init monorepo (`/proto` Python, `/core` Rust, `/docs`) · [ ] add license + README + this roadmap. *Done when:* repo clones and READMEs render.
- [ ] **0.2 Toolchain** — [ ] Python env + lint/format (ruff, black) · [ ] cargo workspace skeleton · [ ] pre-commit hooks. *Done when:* `make check` runs clean.
- [ ] **0.3 CI** — [ ] GitHub Actions running tests on push · [ ] status badge in README. *Done when:* a trivial test goes green in CI.
- [ ] **0.4 Project board** — [ ] create epics from these phases · [ ] import Phase 1 modules as issues. *Done when:* board mirrors this doc.

**Testing.** The pipeline itself is the deliverable, so test the harness: a trivial smoke test (builds + imports) must pass in CI (0.3); a deliberately broken commit (lint error or failing assert) must be **rejected** — verify the gate actually blocks it; confirm pre-commit hooks fire locally (0.2). *Continuous check:* the green CI badge becomes your at-a-glance health signal from here on.

**Timeline:** 1–2 weeks.

---

## Phase 1 — Design database + storage engine  ⭐ *start here*

**Overview.** Build the beating heart: the in-memory model of a design (cells, instances, pins, nets, hierarchy, views) and a **from-scratch storage engine** to persist it durably with undo/history. No heavy math — this is pure data-structures and systems work. Treat the design as a **live, mutable working set**, not a fixed table: instances, nets, and connections are added, moved, deleted, and rewired continuously throughout a session, so the model must grow and shrink cheaply as the user works.

**Key concepts.**
- *Cell* = component/block **type** (blueprint). *Instance* = a placed use of a cell. *Pin* = connection point on a cell/instance. *Net* = set of pins wired together (= one electrical node = a hyperedge).
- *Library* (catalog of cells) vs *design* (instances + nets + hierarchy + views). The design database contains both.
- *Views*: one cell, many representations (symbol / SPICE / footprint / layout).
- Storage-engine internals: pages, B-tree or LSM index, write-ahead log (WAL), crash recovery, append-only/command-log design for free undo & diffing.
- **Dynamic-model principles (design these in from the start):**
  - *Library is read-mostly; the design is read-write and churning.* Placing a part adds an *instance that references* a library cell — never copies it. One cell, many instances.
  - *Nets are a live index, not a recomputation.* Maintain net membership incrementally as pins connect/disconnect; adding one instance or wire must **not** rebuild the whole netlist.
  - *Every edit is a command.* `AddInstance`, `DeleteInstance`, `ConnectPins`, `SplitNet`, etc. The append-only command log **is** the growing history of the design — which is what makes undo/redo (1.6) load-bearing, not optional.
  - *Net merge & split are the hard cases.* Wiring two separate nets together must **fuse** them into one; deleting a wire must **split** a net into two (or a net plus a now-floating pin). Get merge/split right and the rest of the dynamic behavior follows.

**Tools & why.** Python + `networkx` to prototype the graph model quickly; Rust + `petgraph` for the product graph; `serde` for serialization; build the storage engine by hand (learning goal). Study `redb`/`sled` source as reference implementations. R-tree (`rstar`) for spatial queries once geometry appears.

**Resources.**
- *Database Internals* — Alex Petrov (**primary**: pages, B-trees, LSM, WAL, recovery).
- *Designing Data-Intensive Applications* — Kleppmann (storage-engine chapter).
- CMU **15-445/645** (Andy Pavlo) — free lectures + build-a-buffer-pool/B+tree assignments.
- "Let's Build a Simple Database" (cstack) — hands-on SQLite-style store.
- SQLite architecture docs + file-format spec.
- `redb` and `sled` source (Rust embedded stores).
- *Building Git* — Coglan (versioned content-addressed storage → undo/history).
- Cadence **OpenAccess** overview (the industry "one cell, many views" reference).
- KiCad `.kicad_sch`/`.kicad_pcb` S-expression formats (real-world design-DB layout).

**Modules & submodules.**
- [ ] **1.1 Core object model** — [ ] Cell type + view registry · [ ] Instance referencing a cell · [ ] Pin/terminal on cells · [ ] Net (hyperedge over pins) · [ ] Hierarchy (cell contains instances). *Done when:* you can construct the voltage divider (V1, R1, R2, nets vin/out/gnd) in code and query "all pins on net `out`".
- [ ] **1.2 Netlist extraction & queries** — [ ] connectivity queries (pins↔nets↔instances) · [ ] **incremental net index** (update on pin connect/disconnect, no full rebuild) · [ ] **net merge** (wiring two nets fuses them) · [ ] **net split** (deleting a wire breaks a net in two / leaves a floating pin) · [ ] spatial index stub (R-tree) · [ ] flatten hierarchy to a leaf netlist. *Done when:* flattening a 2-level hierarchy yields the correct flat netlist, **and** a merge-then-split sequence returns the net structure to its original state.
- [ ] **1.3 Serialization / file format** — [ ] versioned text format (S-expr/JSON) · [ ] round-trip save/load · [ ] format version field + migration hook. *Done when:* save→load→save is byte-stable and version-tagged.
- [ ] **1.4 Storage engine — persistence** — [ ] page/block manager · [ ] on-disk B-tree (or append-only log) · [ ] key→record store for design objects. *Done when:* a design persists and reloads across process restarts.
- [ ] **1.5 Storage engine — durability** — [ ] write-ahead log · [ ] crash recovery (replay WAL) · [ ] fsync/commit boundaries. *Done when:* a simulated crash mid-write recovers to a consistent state.
- [ ] **1.6 Command log & undo/redo** — [ ] represent every edit as a command (`AddInstance`, `DeleteInstance`, `ConnectPins`, `SplitNet`, `MergeNet`, `MoveInstance`, …) · [ ] append-only history (the log **is** the design's growth over the session) · [ ] undo/redo traversal · [ ] each command carries enough info to invert itself. *Done when:* arbitrary edit sequences — including net merges and splits — undo/redo back to an identical design state.
- [ ] **1.7 Library subsystem** — [ ] cell catalog separate from design · [ ] import/reference cells into a design. *Done when:* two designs share one library cell without duplication.

**Testing.**
- *Unit (1.1, 1.7):* construct the divider; assert pin/net/instance queries; assert instances *reference* (not copy) their library cell.
- *Property / invariant (1.1–1.2, 1.6):* generate random edit sequences and assert invariants after each op — every pin in exactly one net, no dangling references, and undo→redo yields a byte-identical design.
- *Differential oracle (1.2):* after every mutation, compare the incremental net index against a from-scratch recomputation — they must match. This single test guards the whole "nets as a live index" design.
- *Round-trip (1.3):* save→load→save is byte-stable (golden file).
- *Durability / crash (1.4–1.5):* kill the process (or truncate the WAL) at randomized points mid-write; assert recovery to the last committed state; fuzz the crash point.
- *Reference cross-check (1.4):* replay the same op log against a `dict`/SQLite reference store and assert identical reads.

**Timeline:** 8–14 weeks. (1.1–1.3 first as a Python prototype; 1.4–1.6 are the meaty systems work; consider porting 1.1 + 1.4 to Rust once stable.)

---

## Phase 2 — Schematic / logic capture (shared front-end)

**Overview.** A 2D graphics editor whose *output* is connectivity in the Phase 1 database. Shared by both the simulator and the PCB tool. This is where the GUI-framework commitment happens.

**Key concepts.** Infinite zoomable canvas; scene graph; hit-testing & spatial indexing; wire/junction routing → net inference; symbol rendering; undo integration; grid/snapping.

**Tools & why.** Prototype with **PySide6 (Qt) + `QGraphicsView`** — it hands you pan/zoom/selection/undo scaffolding purpose-built for exactly this. For the Rust product, choose **egui** (immediate-mode, lightweight) or **Tauri + WebGPU** (web-tech frontend). R-tree for hit-testing. Study Logisim-evolution and hneemann's *Digital* (both readable Java editors).

**Resources.**
- Qt `QGraphicsView` framework docs.
- KiCad **Eeschema** source.
- **Logisim-evolution** and **Digital** (hneemann) source.
- egui / Slint / Tauri docs (Rust GUI options).

**Modules & submodules.**
- [ ] **2.1 Canvas** — [ ] pan/zoom/grid · [ ] snapping. *Done when:* smooth infinite canvas with grid snap.
- [ ] **2.2 Symbol rendering** — [ ] draw cell symbols from the library · [ ] pin markers. *Done when:* a resistor/source symbol renders with pins.
- [ ] **2.3 Placement & selection** — [ ] place/move/rotate instances · [ ] rubber-band select (R-tree hit-test). *Done when:* place V1/R1/R2 and multi-select works.
- [ ] **2.4 Wiring → nets** — [ ] draw wires · [ ] junction handling · [ ] infer nets into the DB. *Done when:* wiring the divider produces exactly nets vin/out/gnd in the database.
- [ ] **2.5 Undo & persistence integration** — [ ] hook edits into Phase 1 command log · [ ] save/load a schematic. *Done when:* full edit→undo→save→reload cycle is lossless.
- [ ] **2.6 Netlist export** — [ ] emit SPICE-format netlist. *Done when:* exported netlist re-imports identically.

**Testing.**
- *Separate logic from pixels:* keep net-inference headless so wiring-geometry → nets is plain unit-testable (2.4) with no window open.
- *Interaction (2.3–2.5):* drive synthetic mouse/key events with `pytest-qt` / `QTest`; assert the resulting database state.
- *Visual regression (2.1–2.2):* render known schematics to PNG and pixel-diff against approved baselines (`Pillow` diff, or `egui_kittest` for Rust); fail past a threshold.
- *Continuous visual confirmation:* keep a "catalog scene" that draws every symbol and interaction state to eyeball each run; have CI upload the screenshots as build artifacts.
- *Cross-check (2.6):* pipe the exported netlist through ngspice as a validity check.

**Timeline:** 8–16 weeks (GUI work is deceptively large; keep the first canvas minimal).

---

## Phase 3 — Analog simulator (SPICE core)

**Overview.** The math engine. Reads the netlist view and solves the circuit. Stages from *pure linear algebra* (DC) → *calculus* (Newton) → *numerical integration* (transient) → *complex linear algebra* (AC) → device models.

**Key concepts.** Modified Nodal Analysis (MNA) and element "stamping"; sparse LU; Newton–Raphson & companion models; numerical integration (Backward Euler → Trapezoidal → Gear/BDF); local truncation error & adaptive timestep; small-signal AC.

**Tools & why.** Prototype in **Python/SciPy** with **ahkab** as reference (write a working DC+transient SPICE in a few hundred lines). Productize in **Rust (`faer`)** or **C++ (Eigen + KLU)** — KLU because circuit matrices have structure generic solvers waste time on. Regression-test against **ngspice** and analytic answers.

**Resources.**
- Ho, Ruehli & Brennan (1975) — the MNA paper.
- Nagel — SPICE2 thesis.
- *Circuit Simulation* — Najm (**best modern textbook**).
- *The Designer's Guide to SPICE and Spectre* — Kundert.
- KLU paper — Davis & Palamadai.
- `ahkab` (Python) source; ngspice / Xyce (C++) for reference & regression.
- Erik Cheever's MNA write-ups (gentle on-ramp).

**Modules & submodules.**
- [ ] **3.1 Netlist → matrix (DC, linear)** — [ ] node/branch indexing · [ ] resistor stamps · [ ] source stamps (MNA extra rows). *Done when:* divider solves to the analytic node voltages.
- [ ] **3.2 Linear solver** — [ ] dense LU (correctness) · [ ] swap to sparse (KLU/faer). *Done when:* results match with both solvers; sparse is faster on a big net.
- [ ] **3.3 Nonlinear DC (Newton)** — [ ] diode companion model · [ ] Newton loop + convergence (gmin/source stepping). *Done when:* a diode operating point matches ngspice.
- [ ] **3.4 Transient** — [ ] C/L companion models (Backward Euler) · [ ] timestep loop · [ ] adaptive step (LTE). *Done when:* an RC circuit reproduces the analytic charging curve.
- [ ] **3.5 AC / small-signal** — [ ] linearize at operating point · [ ] complex admittances · [ ] frequency sweep. *Done when:* an RC low-pass Bode plot matches theory.
- [ ] **3.6 Device models** — [ ] diode · [ ] BJT (Gummel–Poon) · [ ] MOSFET (square-law → BSIM later). *Done when:* each new model regression-matches ngspice.

**Testing.**
- *Hand-calculated fixtures (3.1, 3.4, 3.5):* voltage divider (Ohm's law), RC step V(t)=V₀(1−e^(−t/RC)), RLC damping/resonance, low-pass −3 dB corner and −20 dB/decade slope — derive by hand, assert within tolerance. This is your "solve it by hand" layer.
- *Per-stamp unit tests (3.1):* assert a resistor/source stamp writes the exact matrix entries.
- *Regression vs ngspice (3.3–3.6):* run the identical netlist in ngspice and diff node voltages/waveforms within tolerance — your primary oracle for nonlinear and device work.
- *Integrator order test (3.4):* integrate dy/dt=−y against e^(−t); halve Δt and confirm the error shrinks at the method's expected order (validates the numerical integration, not just the answer).
- *Conservation (3.4):* a lossless LC tank must keep total energy bounded over long runs.

**Timeline:** 10–20 weeks (3.1–3.4 are the core; 3.6 is effectively bottomless — stop where you like).

---

## Phase 4 — Digital simulator

**Overview.** An event-driven simulator over the same netlist. Numerically trivial vs SPICE — mostly your own small engine.

**Key concepts.** Discrete-event simulation; event/priority queue; signal values & strengths; gate delays; combinational vs sequential; (optional) HDL parsing.

**Tools & why.** Write the event engine yourself. Study **Logisim-evolution** / **Digital** for structure. Add HDL text import later via **`sv-parser`** (Rust) or **ANTLR** grammars; only pull in Verilator/Yosys if synthesis becomes a real requirement.

**Resources.**
- *Digital Design and Computer Architecture* — Harris & Harris.
- *Discrete-Event System Simulation* — Banks.
- Logisim-evolution source; Icarus Verilog (readable event-driven Verilog); Verilator; Yosys.

**Modules & submodules.**
- [ ] **4.1 Value & gate model** — [ ] logic values (0/1/X/Z) · [ ] primitive gates. *Done when:* a NAND truth table is correct.
- [ ] **4.2 Event engine** — [ ] time-ordered queue · [ ] net propagation with delay. *Done when:* a ripple-carry adder settles correctly.
- [ ] **4.3 Sequential elements** — [ ] flip-flops · [ ] clocking. *Done when:* a counter advances on clock edges.
- [ ] **4.4 (Optional) HDL import** — [ ] parse a Verilog subset → netlist. *Done when:* a small Verilog module simulates identically to the graphical version.

**Testing.**
- *Truth tables (4.1):* exhaustively assert every primitive gate.
- *Known circuits (4.2–4.3):* full-adder sums, a counter's sequence, an FSM's transitions — assert the output vectors.
- *Co-simulation cross-check (4.2–4.4):* feed identical stimulus to your engine and to Icarus Verilog / Verilator, then diff the VCD traces.
- *Determinism:* same inputs → identical event ordering across runs (guards against priority-queue ordering bugs).
- *Golden VCD files* for regression.

**Timeline:** 4–8 weeks (excluding optional HDL).

---

## Phase 5 — PCB layout + fabrication output

**Overview.** Heavy computational geometry plus manufacturing export — the branch that reconnects to the physical world (fab houses, CNC mills, ink printers).

**Key concepts.** Geometry kernel (polygons, boolean ops, offsetting); footprints & pad stacks; ratsnest/airwires; placement; interactive routing (defer autorouting); design-rule checking (clearance/width/drill); Gerber (RS-274X) + Excellon output.

**Tools & why.** **Clipper2** for polygon boolean/offset (exactly what clearance/isolation needs) + **R-tree** for DRC queries. Do **interactive routing first**; delegate autorouting to **FreeRouting** or defer it. **Write the Gerber/Excellon exporter by hand** from the Ucamco spec — it's simple and gives full control; that exporter is your bridge to any fab, mill (via FlatCAM/pcb2gcode → G-code → GRBL), or ink printer (Voltera/DragonFly). OpenCASCADE for STEP/3D later.

**Resources.**
- KiCad **Pcbnew** source (**best real-world reference**).
- **Ucamco Gerber** spec (free) + Excellon docs.
- Clipper2; Boost.Geometry / CGAL; `geo`/`rstar` (Rust).
- FreeRouting source.
- *Algorithms for VLSI Physical Design Automation* — Sherwani.
- FlatCAM, pcb2gcode (CAM → machine linkage).

**Modules & submodules.**
- [ ] **5.1 Geometry kernel** — [ ] polygon model · [ ] boolean ops (Clipper2) · [ ] offset. *Done when:* clearance offset of a trace polygon is correct.
- [ ] **5.2 Footprints & mapping** — [ ] footprint view on cells · [ ] netlist→footprint association · [ ] ratsnest. *Done when:* the divider's footprints show correct airwires.
- [ ] **5.3 Placement** — [ ] move/rotate footprints on layers. *Done when:* place all parts on a board outline.
- [ ] **5.4 Interactive routing** — [ ] draw traces on copper layers · [ ] enforce clearance live. *Done when:* route the divider with no clearance violations.
- [ ] **5.5 DRC** — [ ] clearance/width/drill checks over R-tree. *Done when:* DRC flags a deliberately-too-close trace.
- [ ] **5.6 Fabrication export** — [ ] Gerber RS-274X per layer · [ ] Excellon drill. *Done when:* output opens correctly in a third-party Gerber viewer / accepted by a fab preview.
- [ ] **5.7 (Optional) CAM bridge** — [ ] emit G-code isolation toolpaths · [ ] stream to a GRBL machine. *Done when:* a mill cuts a real board from your output.

**Testing.**
- *Geometry units (5.1):* boolean ops/offsets on known polygons, asserting exact area and vertices.
- *Property (5.1):* offset then negative-offset ≈ original (within epsilon); union commutes.
- *DRC fixtures (5.5):* boards seeded with deliberate violations (too-close/thin traces, undersized drills) → assert each is caught; a clean board → zero violations.
- *Manufacturing validation (5.6):* parse your Gerber/Excellon back with `gerbv`/`libgerbv`/`pcb-tools` and compare to the source; run a Gerber linter / fab preflight; export→parse→compare round-trip.
- *Visual regression:* snapshot-diff the rendered board.
- *Physical acceptance (5.7):* mill/print a board and continuity-test it with a multimeter — no shorts, no opens. The ultimate end-to-end test.

**Timeline:** 12–24 weeks (5.4 routing UX and 5.6 export are the big rocks).

---

## Phase 6 — IC / custom layout (lifetime wing)

**Overview.** The Cadence-tier deep end. **Integrate** the mature open-silicon ecosystem rather than rebuilding it; treat GDSII/OASIS as just another view your platform imports/exports.

**Key concepts.** Transistor-level layout; layers & design rules; DRC + **LVS** (Layout Versus Schematic); parasitic extraction; PDKs; GDSII/OASIS, DEF/LEF.

**Tools & why.** **KLayout** (scriptable layout/viewer), **Magic** (layout + DRC), **Netgen** (LVS), **Xschem** (IC schematic), **OpenROAD/OpenLane** (RTL→GDS flow), **Yosys** (synthesis), **OpenSTA** (timing), **ngspice/Xyce** (sim). Free fabbable PDKs: **SkyWater SKY130**, **IHP SG13G2**. Layout I/O via **`gdstk`**. C++/FFI interop expected here.

**Resources.**
- *CMOS VLSI Design* — Weste & Harris.
- *VLSI Physical Design: From Graph Partitioning to Timing Closure* — Kahng, Lienig, Markov, Hu.
- OpenROAD / OpenLane docs; SkyWater PDK docs; KLayout & Magic manuals.

**Modules & submodules.**
- [ ] **6.1 GDSII/OASIS I/O** — [ ] import/export via gdstk as a DB view. *Done when:* a GDS round-trips through your database.
- [ ] **6.2 Layout viewer/editor integration** — [ ] embed/drive KLayout. *Done when:* a cell's layout view opens from your tool.
- [ ] **6.3 DRC/LVS integration** — [ ] Magic DRC · [ ] Netgen LVS against the schematic netlist. *Done when:* LVS passes on a matching layout, fails on a broken one.
- [ ] **6.4 Flow integration** — [ ] drive OpenROAD/OpenLane from a design. *Done when:* a small design reaches GDS.

**Testing.** The silicon tools *are* the harness here:
- *DRC/LVS as tests (6.3):* a correct layout must pass Magic DRC and Netgen LVS; a deliberately-broken one must fail each.
- *GDSII round-trip (6.1):* export→import via `gdstk`→compare geometry.
- *Cross-check (6.2):* diff your DRC results against KLayout's on the same layout.
- *Reference cells:* regress your flow output against known-good SKY130 standard cells.

**Timeline:** 6+ months, open-ended. Add rooms as you're ready.

---

## Cross-cutting concerns (ongoing, every phase)

- **Interchange formats** — SPICE netlist, Verilog/VHDL, Gerber/Excellon, GDSII/OASIS, DEF/LEF, IPC-2581. Supporting them is how the platform interoperates *and* how you bootstrap by importing existing designs.
- **Testing discipline** — property-based tests (`proptest`/Hypothesis) for solvers & geometry; regression suites vs reference tools (ngspice, KiCad, KLayout) and analytic answers; CI green on every push.
- **Performance workflow** — profile before porting; port hot + stable modules Python→Rust via PyO3; keep the Python version as the correctness oracle.
- **Versioning** — schema-version every file format from commit one; append-only history gives undo + diffing for free.

---

## Glossary (for documentation)

- **Cell** — a component/block *type* (blueprint). E.g. "resistor".
- **Instance** — a specific placed use of a cell. E.g. R1, R2 (two instances of "resistor").
- **Pin / terminal / port** — a connection point on a cell/instance.
- **Net** — a set of pins wired together; one electrical node; a hyperedge. Equals a "node" in MNA.
- **Netlist** — the full set of instances + nets (the connectivity).
- **View** — one of a cell's representations (symbol, SPICE model, footprint, layout).
- **Library** — the catalog of cell types (vs the *design*, which is instances + nets + hierarchy).
- **Hierarchy** — cells containing instances of other cells (recursive structure).
- **MNA** — Modified Nodal Analysis; the matrix formulation SPICE solves.
- **Stamp** — an element's contribution to the MNA matrix.
- **Companion model** — a linearized/discretized equivalent of a nonlinear or reactive element used each solver iteration/timestep.
- **DRC** — Design Rule Check (geometry obeys fab rules).
- **LVS** — Layout Versus Schematic (physical layout matches the intended netlist).
- **Gerber / Excellon** — standard PCB copper/drill manufacturing files.
- **GDSII / OASIS** — standard IC layout interchange files.
- **Port (verb)** — re-implement working code in another language/platform.

---

## Suggested GitHub structure

- **Milestones** = Phases 0–6.
- **Epics/labels** = one per phase (`phase-1-database`, `phase-3-sim`, …).
- **Issues (stories)** = Modules (e.g. "1.4 Storage engine — persistence").
- **Sub-issues/tasks** = Submodules (the checkbox items), each closed by its *Done when* test.
- **Board columns** = Backlog → Ready → In progress → In review → Done.
- Tag each issue with an effort estimate; pull from the phase timelines above.

---

*Living document — update effort estimates and tool choices as reality teaches you. The architecture (shared database + views) is the stable part; everything else is negotiable.*
