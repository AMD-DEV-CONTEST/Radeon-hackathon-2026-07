# Specifications

Specifications keep implementation, risks, and verification evidence connected.

Use the change levels in `CONTRIBUTING.md`. `S1` through `S3` use one directory per change:

```text
specs/<module>-<YYMMDD>-<HHMM>/
  PRODUCT.md
  TECH.md
  TEST_REPORT.md  # required for implemented or verified S2/S3 work
```

`TECH.md` must begin with these metadata fields:

```md
- Level: S1
- Status: draft
```

Allowed statuses are `draft`, `ready`, `blocked`, `implemented`, and `verified`.
