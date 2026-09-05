**ATTENTION AI AGENTS:** Do not guess TeaQL API methods! To get the exact API usage and query examples for the entity you are working on, you must fetch the dynamically generated prompt directly from the code generation server. Use your tools to execute the following command to download the exact contextual prompt for the entity:

```bash
cargo teaql --input models/online-bookstore-service.xml java-assist-[action]/[entity-name]
```

Replace `[entity-name]` with the exact entity-name of the entity.

**Available candidate entities in this model:**

| entity-name | display-name |
|-------------|--------------|
| bookstore | Bookstore |
| book | Book |
| book_category | Book Category |


Replace `[action]` with one of the following depending on what you are trying to write:

| action | when-to-use |
|--------|-------------|
| query | You need to read/find records from the database using Q:: |
| create | You need to insert a new record into the database |
| update | You need to modify and save an existing record |
| delete | You need to remove or soft-delete a record |
| expression | You need to safely extract nested relation values (avoiding null panics) using the E:: facade |
| list-page | You need to implement a paginated query returning a SmartList |

Once the command succeeds, read its output. Use the printed code as a template to write your logic.