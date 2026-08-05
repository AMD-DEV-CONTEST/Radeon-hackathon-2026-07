# ts_broken fixture

Used by `tests/intake/test_llm_mocked_intake_repair_lock.py`.

`src/sum.ts` declares a `number` return type but returns a template
string. The TypeScript adapter detects `tsconfig.json` and would
normally invoke `tsc -p .`; the mocked loop never invokes the
toolchain — it only consults the router and feeds canned diagnostics
to the mocked LLM client.
