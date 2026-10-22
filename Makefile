PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3.14)
BUILD_FLAGS ?=

.PHONY: setup cli test-cli build build-hello build-basic build-counter build-counter-session build-my-token build-my-nft build-api-smoke build-ffi-smoke build-dispatch-smoke build-native-unwind build-typed-exports test test-native test-wasm test-live test-all typecheck validate compare
cli:
	cargo build --release --locked

test-cli:
	cargo test --locked

setup:
	uv venv .venv
	uv pip install --python .venv/bin/python -e '.[dev]'
	npm ci --ignore-scripts

build:
	$(PYTHON) scripts/build.py hello $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py basic $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py counter $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py counter_session $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py my_token $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py my_nft $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py api_smoke $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py ffi_smoke $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py dispatch_smoke $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py native_unwind $(BUILD_FLAGS)
	$(PYTHON) scripts/build.py typed_exports $(BUILD_FLAGS)

build-hello:
	$(PYTHON) scripts/build.py hello $(BUILD_FLAGS)

build-counter:
	$(PYTHON) scripts/build.py counter $(BUILD_FLAGS)

build-basic:
	$(PYTHON) scripts/build.py basic $(BUILD_FLAGS)

build-counter-session:
	$(PYTHON) scripts/build.py counter_session $(BUILD_FLAGS)

build-my-token:
	$(PYTHON) scripts/build.py my_token $(BUILD_FLAGS)

build-my-nft:
	$(PYTHON) scripts/build.py my_nft $(BUILD_FLAGS)

build-api-smoke:
	$(PYTHON) scripts/build.py api_smoke $(BUILD_FLAGS)

build-ffi-smoke:
	$(PYTHON) scripts/build.py ffi_smoke $(BUILD_FLAGS)

build-dispatch-smoke:
	$(PYTHON) scripts/build.py dispatch_smoke $(BUILD_FLAGS)

build-native-unwind:
	$(PYTHON) scripts/build.py native_unwind $(BUILD_FLAGS)

build-typed-exports:
	$(PYTHON) scripts/build.py typed_exports $(BUILD_FLAGS)

test: test-native

test-native:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

test-wasm:
	$(PYTHON) -m unittest discover -s tests/wasm -p 'test_*.py' -v

test-live:
	PYTHONPATH=src CSPR_LIVE_TESTS=1 $(PYTHON) -m unittest discover -s tests/live -p 'test_*.py' -v

test-all: build test-native test-wasm test-live

typecheck:
	.venv/bin/python scripts/typecheck.py

validate:
	node scripts/devnet.mjs

compare:
	$(PYTHON) scripts/compare.py
