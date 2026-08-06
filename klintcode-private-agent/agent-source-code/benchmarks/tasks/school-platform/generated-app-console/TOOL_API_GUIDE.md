
# TeaQL Tool API Reference

> [!WARNING]
> **DO NOT GUESS TOOL APIS**
> Do not guess how to use `ctx.http()` or other built-in tool integrations.

> [!IMPORTANT]
> **USE TEAQL'S OWN TOOLING FIRST**
> Always use `cargo teaql` to retrieve assist content. Never bypass the CLI or invoke the generator endpoint directly.

To get the exact API usage and examples for TeaQL Tool APIs, execute the following command:

```bash
cargo teaql --input models/school-service.xml rust-assist-tool-api/[module]
```

> `models/school-service.xml` is the default model path. Adjust if your model file is located elsewhere.

Replace `[module]` with one of the following:

| module | T:: Facade | Description |
|--------|------------|-------------|
| http   | `ctx.http()` | HTTP client for external service calls |

Once the command succeeds, read its output. Use the printed code as a template to write your logic.

## Domain Object Assist APIs

If you need reference code or tool APIs specifically tailored for your domain objects (e.g., `user`, `order`), TeaQL provides code generators that yield perfect, ready-to-copy Rust code snippets.

You can query these assist APIs for any object defined in your `models/school-service.xml`:

| Target | Description | Example Command |
|--------|-------------|-----------------|
| `rust-assist-query/[object]` | How to query and filter `[object]` | `cargo teaql --input models/school-service.xml rust-assist-query/school` |
| `rust-assist-create/[object]` | How to insert/create `[object]` | `cargo teaql --input models/school-service.xml rust-assist-create/school` |
| `rust-assist-update/[object]` | How to update `[object]` | `cargo teaql --input models/school-service.xml rust-assist-update/school` |
| `rust-assist-delete/[object]` | How to delete `[object]` | `cargo teaql --input models/school-service.xml rust-assist-delete/school` |