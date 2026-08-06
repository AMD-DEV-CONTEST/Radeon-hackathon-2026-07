# Bunker test orchestration for local dev and CI.
# Local dev on Windows resolves to the project venv; CI (Linux) uses python3.

ifeq ($(OS),Windows_NT)
PYTHON := .venv310/Scripts/python.exe
else
PYTHON ?= python3
endif

PYTEST := $(PYTHON) -m pytest
BEHAVE := $(PYTHON) -m behave

.PHONY: test-unit test-integration test-eval test-perf test-security test-negative test-compile test-bdd test-all

test-unit:          ## Unit tests (no live model, no eval gate, no perf gate)
	$(PYTEST) tests -m "not integration and not eval and not perf" -q

test-integration:   ## Integration tests (require live local vLLM on :8000)
	$(PYTEST) tests -m integration -q

test-eval:          ## Quality-regression gate over compiled RAG artifact
	$(PYTEST) tests -m eval -q

test-perf:          ## Performance gates (live vLLM + GPU VRAM, env-tunable limits)
	$(PYTEST) tests/test_performance.py -v -m perf

test-security:      ## Prompt-injection and permission "Deny" path tests
	$(PYTEST) tests/test_security_injection.py -v -m integration

test-negative:      ## Graceful-degradation tests for negative paths
	$(PYTEST) tests/test_negative_paths.py -v

test-compile:       ## Smoke test for the offline DSPy compilation script
	$(PYTEST) tests/test_compile_pipeline.py -v

test-bdd:           ## Behavior tests (behave / Gherkin)
	$(BEHAVE) tests/features/

test-all: test-unit test-integration test-eval test-perf test-security test-negative test-compile test-bdd
