# TEAQL WARNING: This project uses TeaQL. TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
# AI AGENTS MUST STRICTLY USE THESE MAKE TARGETS ONLY. Do NOT guess other build commands.

.PHONY: build test run clean help generate-lib

# Default target
help:
	@echo "Available commands:"
	@echo "  make generate-lib - Regenerate the TeaQL domain library"
	@echo "  make build        - Build the Spring Boot application (mvn clean package)"
	@echo "  make test         - Run application tests (mvn test)"
	@echo "  make run          - Run the application locally (mvn spring-boot:run)"
	@echo "  make clean        - Clean the project"

generate-lib:
	@echo "Regenerating TeaQL library..."
	./gen-lib.sh || echo "Please ensure gen-lib.sh exists or run teaql code generator manually"

build:
	mvn clean package -DskipTests

test:
	mvn test

run:
	mvn spring-boot:run

clean:
	mvn clean