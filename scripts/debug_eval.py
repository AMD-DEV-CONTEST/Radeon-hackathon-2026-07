"""Debug script: test single NL→DSL case end-to-end."""
import sys, ast, yaml
sys.path.insert(0, '.')

from scripts.eval_nl_to_dsl import call_vllm, extract_yaml, TEST_PROMPTS
from src.dsl.canonicalizer import canonicalize_dsl
from src.dsl.transpiler import transpile_to_freqtrade
from src.dsl.validator import validate_dsl

VLLM_URL = "http://localhost:8000/v1"
MODEL = "models/qwen-trader-merged"

for tc in TEST_PROMPTS[:3]:
    print(f"\n{'='*60}")
    print(f"Test: {tc['id']} | {tc['nl'][:60]}")

    out = call_vllm(VLLM_URL, "Output ONLY valid YAML.", tc["nl"], model=MODEL)
    print(f"RAW[:300]: {out[:300]}")

    dsl = extract_yaml(out)
    if not dsl:
        print("EXTRACT FAILED")
        continue

    print(f"Strategy name: {dsl.get('strategy',{}).get('name','?')}")

    canon, repairs, errors = canonicalize_dsl(dsl)
    print(f"Canon errors: {errors}")
    for r in repairs:
        print(f"  REPAIR: {r.field}: {r.raw} -> {r.normalized} ({r.repair_type})")

    valid, verrors = validate_dsl(canon)
    print(f"Valid: {valid}, Errors: {verrors[:2]}")

    try:
        code = transpile_to_freqtrade(canon)
        ast.parse(code)
        print("TRANSPILE: OK")
    except Exception as e:
        print(f"TRANSPILE ERR: {e}")

    inds = canon.get('strategy', {}).get('indicators', [])
    actual = {i.get('name') for i in inds}
    expected = tc.get('expected_indicators', set())
    print(f"Indicators actual: {actual}")
    print(f"Indicators expected: {expected}")
    print(f"Match: {expected.issubset(actual)}")
