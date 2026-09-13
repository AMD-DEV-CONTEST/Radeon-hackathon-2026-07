.PHONY: up down logs migrate test bench

up: ## Start the full stack (Postgres, Redis, vLLM/ROCm, backend, frontend)
	docker compose up --build -d
	docker compose run --rm migrate

down:
	docker compose down

logs:
	docker compose logs -f backend

migrate: ## Run Alembic migrations against a running Postgres
	docker compose run --rm migrate

test: ## Run the backend test suite (no external infra needed — uses SQLite)
	cd backend && python -m pytest tests/ -v

bench: ## Run the ROCm/vLLM GPU benchmark against a running vllm service
	python benchmarks/benchmark_inference.py --concurrency 1 4 8 16
