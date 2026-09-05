# TeaQL Runtime Customization Guide

> [!WARNING]
> **DO NOT GUESS RUNTIME CONFIGURATION**
> Do not guess how to configure the runtime, connection pools, or schema generation.

To get the exact usage and examples for Customizing the Runtime (UserContext assembly, SQL debugging, Schema modes), you must fetch the dynamically generated prompt directly from the code generation server. Use your tools to execute the following command:

```bash
cargo teaql --input models/online-bookstore-service.xml java-assist-runtime-custom
```

Once the command succeeds, read its output. Use the printed code as a template to write your logic.