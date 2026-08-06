# TEAQL WARNING: This project uses TeaQL. TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
# AI AGENTS MUST STRICTLY USE THESE MAKE TARGETS ONLY. Do NOT guess other build commands.

.PHONY: build test run clean help rust-lib-core

help:
	@echo "Available commands:"
	@echo "  make rust-lib-core - Regenerate the TeaQL domain library"
	@echo "  make build        - Build the Rust application (cargo build)"
	@echo "  make test         - Run application tests (cargo test)"
	@echo "  make run          - Run the application locally (cargo run)"
	@echo "  make clean        - Clean the project"

rust-lib-core:
	@echo "Regenerating TeaQL library..."
	./gen-lib.sh || echo "Please ensure gen-lib.sh exists or run teaql code generator manually"

build:
	cargo check && cargo build

test:
	cargo test

run:
	cargo run

clean:
	cargo clean