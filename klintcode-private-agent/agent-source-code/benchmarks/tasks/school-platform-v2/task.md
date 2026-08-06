# School Management System

Use Rust (KSML) to build a school management system with these domain concepts:
- Platform
- School
- School Type, with values Primary and Secondary

Create the semantic TeaQL model first (in a single main.xml file), review it, then generate the Rust TeaQL code (Cargo project). Finally, test some of Q and E api and generate a running report.

## Requirements
- Output a single complete XML document for the KSML model
- Follow the grammar example structure
- Generate the Rust code using `cargo teaql generate` or similar tools
- Write a simple Rust test or report showing Q and E api usage

## CRITICAL BEHAVIORAL RULES
1. **Never guess method names or randomly grep source code**: Do not blindly search other directories (like moving-company-platform) for API usage.
2. **Read the Docs**: Once you run `cargo teaql generate`, a local `AGENTS.md` file will be generated in the output workspace (e.g., `generated-app-console/AGENTS.md`). You MUST use the `read_file` tool to read this file before writing any TeaQL business code. It contains all the API examples you need.
3. If you cannot find what you need in the local `AGENTS.md`, stop and call `finish_task`. Do NOT fall into a loop of grepping files.
