SHELL := /usr/bin/env bash
PYTHON ?= python3

.PHONY: preflight install-bigym build-gsplat build-opensplat smoke-gsplat download-reference-data reconstruct reconstruct-rocm smoke-reconstruction stage-shell collect validate clean verify verify-evaluation verify-pipeline eval-preflight eval-bootstrap eval-download-shell eval-probe eval-smoke eval-formal

preflight:
	./scripts/preflight_rocm.sh

install-bigym:
	./scripts/install_bigym_overlay.sh

build-gsplat:
	./scripts/build_gsplat_rocm.sh

build-opensplat:
	./reconstruction/bin/build_rocm_opensplat_gfx1100.sh \
		"$${OPENSPLAT_SOURCE:?set OPENSPLAT_SOURCE}"

smoke-gsplat:
	"$${VENV:?set VENV}/bin/python" scripts/smoke_test_gsplat.py

download-reference-data:
	./reconstruction/bin/download_reference_data.sh

reconstruct:
	./reconstruction/bin/reconstruct.sh

reconstruct-rocm:
	./reconstruction/bin/reconstruct_rocm.sh

smoke-reconstruction:
	@set -e; \
	tmp_dir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp_dir"' EXIT; \
	"$(PYTHON)" reconstruction/src/make_synthetic_fixture.py --output "$$tmp_dir/input"; \
	"$(PYTHON)" reconstruction/src/export_scene_shell.py \
		--input "$$tmp_dir/input/gaussians.ply" \
		--camera-path "$$tmp_dir/input/camera-path.json" \
		--alignment "$$tmp_dir/input/alignment.json" \
		--source-report "$$tmp_dir/input/source.json" \
		--output "$$tmp_dir/shell" >/dev/null; \
	"$(PYTHON)" reconstruction/src/verify_shell_export.py "$$tmp_dir/shell"
	"$(PYTHON)" scripts/test_reconstruction_contracts.py

stage-shell:
	./scripts/stage_visual_shell.sh

collect:
	./scripts/run_cutlery32.sh

validate:
	"$${VENV:?set VENV}/bin/python" scripts/validate_lerobot_v3_collection.py \
		"$${DATASET_ROOT:?set DATASET_ROOT}" --workers "$${VALIDATION_WORKERS:-4}"

clean:
	@echo "Run scripts/clean_gaussian_ply.py once per PLY; see docs/04-validation-and-cleaning.md"

verify:
	./scripts/verify_public_repo.sh

verify-evaluation:
	./evaluation/bigym-3dgs/bin/verify.sh

verify-pipeline: verify-evaluation

eval-preflight:
	./evaluation/bigym-3dgs/bin/preflight_amd.sh

eval-bootstrap:
	./evaluation/bigym-3dgs/bin/bootstrap_bigym_source.sh
	./evaluation/bigym-3dgs/bin/bootstrap_bigym_runtime.sh

eval-download-shell:
	./evaluation/bigym-3dgs/bin/download_shell.sh

eval-probe:
	./evaluation/bigym-3dgs/bin/probe_inference.sh

eval-smoke:
	./evaluation/bigym-3dgs/bin/run_eval.sh smoke

eval-formal:
	./evaluation/bigym-3dgs/bin/run_eval.sh formal
