.PHONY: check-governance check-specs check-pr-title test-governance

check-governance:
	git diff --check
	python scripts/validate_specs.py --strict

check-specs:
	python scripts/validate_specs.py --strict

check-pr-title:
	@test -n "$(TITLE)" || (echo "Usage: make check-pr-title TITLE='Track 2, Team, App'" && exit 2)
	python scripts/validate_pr_title.py --title "$(TITLE)"

test-governance:
	python -m unittest discover -s tests -p 'test_*.py'
