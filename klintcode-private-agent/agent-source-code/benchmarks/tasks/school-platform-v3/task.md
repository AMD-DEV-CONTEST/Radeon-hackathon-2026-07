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

## 🚨 ABSOLUTE STRICT RULES (绝对红线)
1. **Never guess method names**: Do not blindly guess SDK method names.
2. **Read the Docs**: Once you run `cargo teaql generate`, a local `AGENTS.md` file will be generated in the output workspace (e.g., `generated-app-console/AGENTS.md`). You MUST use the `read_file` tool to read this file. It contains all the API examples you need.
3. **DO NOT READ GENERATED SOURCE CODE**: You are strictly FORBIDDEN from reading, viewing, or grepping ANY `.rs` files inside the generated workspaces (`rust-lib-core`, `generated-app-console`, etc.) to learn the SDK. 
4. **Trust AGENTS.md**: The SDK documentation is fully provided in `AGENTS.md`. Rely ONLY on that file to write your Q and E API code. Once you read it, write your code and call `finish_task`. DO NOT over-explore or fall into a loop of grepping `.rs` files!
