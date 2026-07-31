
# Unified EDA Platform

![CI](https://github.com/sumaJonathan/eda-platform/actions/workflows/ci.yml/badge.svg)

A platform that combines analog simulation, digital simulation, PCB
design, and custom IC layout on one design database.

> **Status: Phase 0 — Foundations.** See
> [`docs/eda_platform_roadmap.md`](docs/eda_platform_roadmap.md) for the full project plan.

## Repository layout

| Path      | Language | Purpose                                                        |
|-----------|----------|----------------------------------------------------------------|
| `proto/`  | Python   | Rapid prototypes and the correctness *oracle* for ported code  |
| `core/`   | Rust     | The product core — performance-critical, memory-safe modules   |
| `docs/`   | —        | Roadmap and design notes                                       |

The workflow is **prototype in Python, port the stable modules to Rust**,
validating each Rust module against the Python version. See the roadmap's
guiding principles for the rationale.

## Quick start

### Python prototype (`proto/`)

```bash
cd proto
uv venv                       # or: python -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"    # or: pip install -e ".[dev]"
pytest
```

### Rust core (`core/`)

```bash
cd core
cargo build
cargo test
```

### Both at once

```bash
make check    # format-check, lint, and test both languages
```

## License

MIT — see [`LICENSE`](LICENSE).
