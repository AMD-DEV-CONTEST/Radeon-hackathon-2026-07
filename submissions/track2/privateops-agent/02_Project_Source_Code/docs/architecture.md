# Permission-First Architecture

The current architecture is defined in two synchronized reviewer artifacts:

- `submission/assets/architecture.svg` and `submission/assets/architecture.png` - reviewer-facing diagram.
- `submission/PrivateOps-Agent-Project-Specification.pdf` - complete competition narrative.

The runtime is split into configuration, bilingual retrieval, planning, guarded tools, permission tokens, local memory, model providers, append-only audit, benchmark evidence, HTTP service, and a no-build browser trust console. Broad supported observation and deliberate action meet at the permission kernel: safe read-only tools execute, supported side effects wait for exact confirmation, and unsafe requests remain blocked.
