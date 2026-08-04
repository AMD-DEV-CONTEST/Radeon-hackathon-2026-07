.PHONY: bootstrap install check test lint format dev dev-api dev-web build-web \
	test-web check-web e2e install-e2e-browser demo-data validate-evals benchmark \
	radeon-start radeon-stop radeon-health radeon-validate

UV_CACHE_DIR ?= .cache/uv
PYTHON ?= .venv/bin/python
PNPM ?= pnpm

bootstrap:
	@if [ -x /opt/venv/bin/python ]; then \
		./scripts/bootstrap-cloud.sh; \
	else \
		$(MAKE) install; \
	fi

install:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --extra dev --frozen
	$(PNPM) install --frozen-lockfile

check: lint test test-web check-web build-web

test:
	$(PYTHON) -m pytest

lint:
	.venv/bin/ruff check src tests scripts benchmarks ops/radeon/validate-runtime.py
	.venv/bin/mypy src

format:
	.venv/bin/ruff format src tests scripts benchmarks ops/radeon/validate-runtime.py
	.venv/bin/ruff check --fix src tests scripts benchmarks ops/radeon/validate-runtime.py

dev:
	$(MAKE) -j2 dev-api dev-web

dev-api:
	.venv/bin/uvicorn policyseal.api.app:app --app-dir src --host 127.0.0.1 --port 8787 --reload

dev-web:
	$(PNPM) run dev:web

test-web:
	$(PNPM) run test:web

check-web:
	$(PNPM) run check:web

build-web:
	$(PNPM) run build:web

e2e:
	$(PNPM) run e2e

install-e2e-browser:
	$(PNPM) --filter @policyseal/web exec playwright install chromium

demo-data:
	$(PYTHON) scripts/generate_demo_data.py

validate-evals:
	$(PYTHON) scripts/validate_evals.py

benchmark:
	$(PYTHON) ops/radeon/validate-runtime.py --require-model-server --output var/radeon/runtime-validation.json
	$(PYTHON) -m benchmarks.run_analysis --runtime var/radeon/runtime-validation.json

radeon-start:
	./ops/radeon/start-services.sh

radeon-stop:
	./ops/radeon/stop-services.sh

radeon-health:
	./ops/radeon/health-check.sh

radeon-validate:
	$(PYTHON) ops/radeon/validate-runtime.py --output var/radeon/runtime-validation.json
