# Convenience targets for RadeonVLA-Reflex
# Usage: make help

.PHONY: help install-local check download-demo download-all smoke record-local record-basic expert-demo reflex-demo remote-check remote-full audit docker-build docker-check

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

help:
	@echo "RadeonVLA-Reflex — common targets"
	@echo ""
	@echo "  make install-local   # pip install -e . + local requirements (torch separate)"
	@echo "  make check           # env + audit + pytest + ruff"
	@echo "  make download-demo   # pinned Physical-1K + 20K model + evidence"
	@echo "  make download-all    # all public datasets, models, and evidence"
	@echo "  make smoke           # 1-episode end-to-end smoke"
	@echo "  make record-local    # record a few local episodes (SUITE/EPISODES overridable)"
	@echo "  make record-basic    # all 20 fruit/bowl combinations + validation"
	@echo "  make expert-demo     # scripted demos (MODE=mix|basic|hard)"
	@echo "  make reflex-demo     # normal + interrupt + target-shift model demos (needs CKPT)"
	@echo "  make all-local       # full local one-click record pipeline"
	@echo "  make remote-check    # strict AMD gate (on Radeon machine)"
	@echo "  make remote-full     # full AMD train/eval pipeline"
	@echo "  make audit           # release structure audit only"
	@echo "  make docker-build    # build the self-contained ROCm image"
	@echo "  make docker-check    # run strict AMD checks inside the image"
	@echo ""
	@echo "Examples:"
	@echo "  EPISODES=20 SUITE=basic make record-local"
	@echo "  MODE=hard make expert-demo"
	@echo "  EPISODES=200 SUITE=basic make remote-full"

install-local:
	python -m pip install -r requirements.local.txt
	python -m pip install -e .

check:
	bash scripts/check_local.sh

download-demo:
	python -m radeonvla.download_artifacts --artifact physical-1k model-20k evaluation-videos

download-all:
	python -m radeonvla.download_artifacts --all

smoke:
	bash scripts/run_pipeline_smoke.sh

record-local:
	bash scripts/run_record.sh

record-basic:
	EPISODES=$${EPISODES:-20} SUITE=basic bash scripts/run_record.sh

expert-demo:
	bash scripts/run_expert_demo.sh

reflex-demo:
	bash scripts/run_reflex_demo.sh

all-local:
	bash scripts/run_all_local.sh

remote-check:
	bash scripts/check_remote_amd.sh

remote-full:
	bash scripts/run_full_remote.sh

audit:
	python -m radeonvla.submission_audit

docker-build:
	docker build --pull -f docker/Dockerfile -t radeonvla-reflex:rocm7.2.1 .

docker-check:
	docker compose -f docker/compose.yaml run --rm radeonvla check-amd
