.PHONY: test demo validate

test:
	python3 -m unittest discover -s tests -v

demo:
	python3 -m autotuner demo artifacts/sample_run

validate:
	python3 -m autotuner validate configs/radeon.json
