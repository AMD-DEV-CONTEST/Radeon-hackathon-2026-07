.PHONY: install demo benchmark test clean

install:
	pip install -e .
	pip install -r requirements.txt

demo:
	python -m src.ui.app

productivity:
	python examples/productivity_assistant.py

copilot:
	python examples/developer_copilot.py

research:
	python examples/multi_agent_research.py

benchmark:
	python scripts/benchmark_rocm.py

test:
	pytest tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf data/chroma_db data/chroma_rag .pytest_cache
