# TeaQL Tool API Reference

> [!WARNING]
> **DO NOT GUESS TOOL APIS**
> Do not guess how to use `ctx.http()` or other built-in tool integrations.

To get the exact API usage and examples for TeaQL Tool APIs, execute the following command:

```bash
cargo teaql --input models/platform-modules.xml rust-assist-tool-api/[module]
```

> `models/platform-modules.xml` is the default model path. Adjust if your model file is located elsewhere.

Replace `[module]` with one of the following:

| module | T:: Facade | Description |
|--------|------------|-------------|
| http   | `ctx.http()` | HTTP client for external service calls |

Once the command succeeds, read its output. Use the printed code as a template to write your logic.

## Domain Object Assist APIs

If you need reference code or tool APIs specifically tailored for your domain objects (e.g., `user`, `order`), TeaQL provides code generators that yield perfect, ready-to-copy Rust code snippets.

You can query these assist APIs for any object defined in your `models/platform-modules.xml`:

| Target | Description | Example Command |
|--------|-------------|-----------------|
| `rust-assist-query/[object]` | How to query and filter `[object]` | `cargo teaql rust-assist-query/school` |
| `rust-assist-create/[object]` | How to insert/create `[object]` | `cargo teaql rust-assist-create/school` |
| `rust-assist-update/[object]` | How to update `[object]` | `cargo teaql rust-assist-update/school` |
| `rust-assist-delete/[object]` | How to delete `[object]` | `cargo teaql rust-assist-delete/school` |

### Bypassing CLI with cURL

If you prefer to bypass the CLI client entirely (for example, to avoid any local parameter parsing issues), you can send your model file directly to the TeaQL endpoint using `curl`. This approach is extremely fast and cleanly returns the formatted markdown:

```bash
curl -X POST -F "file=@models/platform-modules.xml" https://api.teaql.io/latest/teaql/rust-assist-query/school
```
(Replace `rust-assist-query/school` with any valid assist target.)