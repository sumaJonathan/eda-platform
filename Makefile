.PHONY: help setup fmt lint test check clean

help:
	@echo "Targets:"
	@echo "  setup  - install Python dev deps and fetch Rust deps"
	@echo "  fmt    - auto-format Python (ruff) and Rust (cargo fmt)"
	@echo "  lint   - lint Python (ruff) and Rust (clippy)"
	@echo "  test   - run pytest and cargo test"
	@echo "  check  - format-check + lint + test (what CI runs)"
	@echo "  clean  - remove build/test caches"

setup:
	cd proto && uv venv && uv pip install -e ".[dev]"
	cd core && cargo fetch

fmt:
	cd proto && ruff format .
	cd core && cargo fmt

lint:
	cd proto && ruff check .
	cd core && cargo clippy --all-targets -- -D warnings

test:
	cd proto && pytest
	cd core && cargo test

check:
	cd proto && ruff format --check . && ruff check . && pytest
	cd core && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

clean:
	cd core && cargo clean
	rm -rf proto/.pytest_cache proto/.ruff_cache proto/.hypothesis
