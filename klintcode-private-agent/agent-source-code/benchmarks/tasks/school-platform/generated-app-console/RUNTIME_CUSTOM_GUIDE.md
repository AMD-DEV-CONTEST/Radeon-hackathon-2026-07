
# TeaQL Runtime & Framework API Reference

> [!WARNING]
> **DO NOT GUESS FRAMEWORK APIS**
> Do not guess how to use `UserContext`, `SmartList`, `WebResponse`, or how to manage transactions, schema, and save pipelines.

To get the exact API usage and examples for Runtime & Framework APIs (UserContext, SmartList, WebResponse, AuditConfig, Save Pipeline, Value Types, etc.), you must fetch the dynamically generated prompt directly from the code generation server. Use your tools to execute the following command:

```bash
cargo teaql --input models/school-service.xml rust-assist-runtime-custom
```

> `models/school-service.xml` is the default model path. Adjust if your model file is located elsewhere.

Once the command succeeds, read its output. Use the printed code as a template to write your logic.