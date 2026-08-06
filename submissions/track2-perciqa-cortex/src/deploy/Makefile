.PHONY: up down build logs broker

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

broker:
	python -m cortex.broker.server --host 0.0.0.0 --port 7432 --registry ./registry/org_registry.json

test:
	python -m pytest tests/ -x --tb=short
