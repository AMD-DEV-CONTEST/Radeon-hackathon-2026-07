# E-Sentinel Testing Guide

## Quick Start

```bash
# Install dependencies (if not already done)
npm install

# Run all tests (unit + integration + type check)
bash scripts/run-all-tests.sh

# Or run individual test suites:
npm run test              # All tests
npm run test:unit         # Unit tests only (src/lib)
npm run test:integration  # Integration tests only (src/app/api)
npm run test:coverage     # All tests with coverage report
npm run test:precommit    # Only changed files (fast)
npm run test:ci           # CI mode with coverage JSON
```

## Test Structure

```
src/
├── lib/
│   └── __tests__/
│       ├── json-diff.test.ts          # JSON diff utility (10 tests)
│       ├── parse-llm-response.test.ts # LLM response parser (14 tests)
│       ├── audit.test.ts              # Audit log types and functions (4 tests)
│       ├── utils.test.ts              # formatPercent, cn (11 tests)
│       └── correlation.test.ts        # Correlation ID generation (4 tests)
└── app/api/qa/
    └── __tests__/
        ├── bot-configs-pending.test.ts  # Pending configs endpoint (4 tests)
        └── knowledge-pending.test.ts    # Pending knowledge endpoint (3 tests)
```

## Test Commands Reference

| Command | Description | Expected Output |
|---------|-------------|-----------------|
| `npm test` | Run all 56 tests | 7 suites, 56 tests, all green |
| `npm run test:unit` | Run 43 lib tests | 5 suites, 43 tests, all green |
| `npm run test:integration` | Run 13 API tests | 2 suites, 13 tests, all green |
| `npm run test:coverage` | All tests + coverage | Coverage report with thresholds (branches:85% functions:90% lines:90%) |
| `npm run test:precommit` | Only changed files | Fast gate before commit |
| `npx tsc --noEmit` | TypeScript check | Zero type errors |

## Coverage Targets

| Metric | Target |
|--------|--------|
| Branches | 85% |
| Functions | 90% |
| Lines | 90% |

## Test Patterns

### Unit Tests (Pure Functions)

```typescript
import { myFunction } from "../my-module";

describe("myFunction", () => {
  it("handles normal input", () => {
    expect(myFunction("input")).toBe("expected");
  });

  it("handles edge case", () => {
    expect(myFunction("")).toBeNull();
  });
});
```

### Integration Tests (API Routes)

```typescript
jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));

describe("GET /api/qa/my-endpoint", () => {
  it("returns 500 when Supabase is not configured", async () => {
    const { GET } = require("../my-endpoint/route");
    const res = await GET(new Request("http://localhost:3000/api/qa/my-endpoint"));
    expect(res.status).toBe(500);
  });
});
```

## CI Integration

```bash
# In your CI pipeline:
npm ci
bash scripts/run-all-tests.sh --ci
```

CI mode (`--ci`):
- Fails immediately on TypeScript errors
- Fails immediately on unit test failures
- Generates coverage JSON for CI dashboard integration

## Writing New Tests

1. **Unit tests**: Create `src/lib/__tests__/<module-name>.test.ts`
2. **Integration tests**: Create `src/app/api/qa/__tests__/<endpoint>.test.ts`
3. Follow existing patterns for mocking `@/lib/supabase` and `nanoid`
4. Ensure `npx tsc --noEmit` passes after adding tests
5. Run `npm test` to verify all existing tests still pass

## Known Limitations

- **Supabase query chain mocking**: The Supabase PostgrestFilterBuilder uses a thenable chain pattern that is not fully mockable in Jest. Integration tests focus on input validation, error handling, and boundary conditions rather than full database query simulation.
- **nanoid ESM**: The `nanoid` package is ESM-only. A manual mock is configured in `jest.config.ts` (`moduleNameMapper`) and `__mocks__/nanoid.js`.
- **Full e2e tests**: E2E tests requiring a running Supabase instance are planned for a future test phase. Run them manually with `scripts/test-full-flow.mjs`.
