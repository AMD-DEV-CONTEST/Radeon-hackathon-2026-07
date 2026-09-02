.PHONY: verify fixture-up fixture-down radeon-local-up championship-up stack-down \
	mission-control-up mission-control-down stack-status stack-logs evidence-export \
	radeon-exporter observability-check container-check

verify:
	scripts/verify.sh

fixture-up:
	scripts/prepare_container_secrets.sh
	docker compose --profile fixture up --detach --build signalforge

fixture-down:
	docker compose --profile fixture down

radeon-local-up:
	scripts/prepare_container_secrets.sh
	docker compose --profile radeon-local --profile observability up --detach --build

championship-up:
	scripts/prepare_container_secrets.sh
	docker compose --profile championship --profile observability up --detach --build

stack-down:
	docker compose --profile fixture --profile radeon-local --profile championship \
		--profile observability down

mission-control-up:
	scripts/prepare_container_secrets.sh
	docker compose --profile fixture --profile observability up --detach --build

mission-control-down:
	docker compose --profile fixture --profile observability down

stack-status:
	docker compose --profile fixture --profile radeon-local --profile championship \
		--profile observability ps

stack-logs:
	docker compose --profile fixture --profile radeon-local --profile championship \
		--profile observability logs --tail=200

evidence-export:
	python3 scripts/export_mission_control_evidence.py \
		--audit-dir .signalforge/intelligence-audit \
		--output output/mission-control-evidence.tar.gz

radeon-exporter:
	RADEON_EXPORTER_HOST=127.0.0.1 python3 deploy/observability/radeon-exporter/exporter.py

observability-check:
	python3 scripts/validate_observability.py

container-check:
	scripts/verify_container_fixture.sh
