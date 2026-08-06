# TeaQL Tool & Runtime API Reference

> [!WARNING]
> **DO NOT GUESS FRAMEWORK APIS**
> Do not guess how to use `UserContext`, `SmartList`, `WebResponse`, or how to manage transactions.

To get the exact API usage and examples for Framework-level APIs (UserContext, SmartList, WebResponse, Entity Expression, Checkers, etc.), you must fetch the dynamically generated prompt directly from the code generation server. Use your tools to execute the following command:

```bash
cargo teaql --input models/online-bookstore-service.xml java-assist-tool-api
```

Once the command succeeds, read its output. Use the printed code as a template to write your logic.

## Domain Object Assist APIs

If you need reference code or tool APIs specifically tailored for your domain objects (e.g., `user`, `order`), TeaQL provides code generators that yield perfect, ready-to-copy Java code snippets.

You can query these assist APIs for any object defined in your `models/online-bookstore-service.xml`:

| Target | Description | Example Command |
|--------|-------------|-----------------|
| `java-assist-query/[object]` | How to query and filter `[object]` | `cargo teaql java-assist-query/school` |
| `java-assist-create/[object]` | How to insert/create `[object]` | `cargo teaql java-assist-create/school` |
| `java-assist-update/[object]` | How to update `[object]` | `cargo teaql java-assist-update/school` |
| `java-assist-delete/[object]` | How to delete `[object]` | `cargo teaql java-assist-delete/school` |

### Bypassing CLI with cURL

If you prefer to bypass the CLI client entirely (for example, to avoid any local parameter parsing issues), you can send your model file directly to the TeaQL endpoint using `curl`. This approach is extremely fast and cleanly returns the formatted markdown:

```bash
curl -X POST -F "file=@models/online-bookstore-service.xml" https://api.teaql.io/latest/teaql/java-assist-query/school
```
(Replace `java-assist-query/school` with any valid assist target.)