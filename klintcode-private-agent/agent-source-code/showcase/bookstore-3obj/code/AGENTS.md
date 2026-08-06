# TeaQL Java Agent Instructions

> [!WARNING]
> **IGNORE GENERIC ORM EXPERIENCE**
>
> Do **not** use pre-trained habits from data-access frameworks, ORMs, or database integration libraries.
>
> Do **not** use MyBatis, JPA, Hibernate, Spring Data, MyBatis-Plus, or similar frameworks.
>
> Do **not** write raw SQL, DAOs, Repository implementations, or custom persistence layers.
>
> Do **not** guess TeaQL method names.

## How to Write Domain Code

To get the exact API usage and query examples for the entity you are working on, execute the following command:

```bash
cargo teaql --input models/online-bookstore-service.xml java-assist-[action]/[entity-name]
```

> `models/online-bookstore-service.xml` is the default model path. If the model file is located elsewhere, adjust the `--input` path to match the actual file location in this project.

Replace `[action]` with one of the following:

| action | when-to-use |
|--------|-------------|
| query | Read/find records from the database using Q. |
| create | Insert a new record into the database |
| update | Modify and save an existing record |
| delete | Remove or soft-delete a record |
| expression | Safely extract nested relation values using E. |
| list-page | Implement a paginated query returning SmartList |
| debug | View instructions for enabling SQL logging and debugging |

Replace `[entity-name]` with the exact entity-name from the table below:

| entity-name | display-name |
|-------------|--------------|
| bookstore | Bookstore |
| book | Book |
| book_category | Book Category |


Once the command succeeds, read its output. Use the printed code as a template to write your logic.

If the command cannot be executed, stop and report the missing context. Do not invent APIs.

## Additional References

Read these only when the task requires them:

* **`TOOL_API_GUIDE.md`**
  Framework runtime references and context handling.

* **`RUNTIME_CUSTOM_GUIDE.md`**
  Runtime setup, debugging, and project-specific restrictions.