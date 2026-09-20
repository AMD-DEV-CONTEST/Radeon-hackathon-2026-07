"""Memory consistency test framework.

Packages: tests/memory_consistency
  scenarios.json        — 10 scenarios (prompts + judge rules + goldens)
  scenarios_data.py     — golden tables for the mock adapter
  judge.py              — rule-based judgment engine (zero deps)
  runner.py             — CLI runner (mock self-check / react real agent)
  adapters/mock.py      — fake agent: correct (all PASS) / confused (all FAIL)
  adapters/react.py     — real ReAct agent wrapper (delayed import)
"""
