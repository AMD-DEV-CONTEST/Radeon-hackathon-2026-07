# TeaQL Java CRUD Guide

Generated for `com.doublechaintech.onlinebookstoreservice`. Use this guide when adding controllers, services, jobs, or integration code in this workspace.

## Setup

```java
import com.doublechaintech.onlinebookstoreservice.Q;
import com.doublechaintech.onlinebookstoreservice.OnlineBookstoreServiceUserContext;
import io.teaql.core.web.WebResponse;
```

Most workspace code receives a TeaQL context from Spring:

```java
public WebResponse handle(@TQLContext UserContext userContext) {
    // use Q, WebResponse, and entity.auditAs("comment").save(userContext)
}
```

## Non-Negotiable Database Rule

Never use SQL to operate on the database from workspace business code. This includes select, insert, update, delete, schema changes, JDBC templates, native queries, direct repositories, and ad hoc SQL helpers.

If the generated TeaQL API does not provide a path for the requested change, stop and report the missing API. Do not implement a SQL workaround.

## Mandatory Update Method Rule

Use generated `updateXxx(...)` methods for all entity field changes. Do not use `setXxx(...)` in new code. Setters are deprecated even when the IDE or generated class makes them visible.

```java
entity.updateName("new value");
```

Do not write:

```java
entity.setName("new value");
```

## Read One Entity

Prefer typed generated query entry points. Controller methods that return one object should wrap the result in `WebResponse.of(...)`:

```java
public WebResponse getOne(@TQLContext UserContext userContext, Long id) {
    try {
        var entity = Q.bookstores()
            .filterById(id)
            .selectSelf()
            .comment("load detail by id")
            .purpose("get task detail")
            .executeForOne(userContext);
        return WebResponse.of(entity);
    } catch (Exception e) {
        return WebResponse.fail(e.getMessage());
    }
}
```

## Read A Page

Controller methods that return multiple objects should wrap the list in `WebResponse.of(...)`:

```java
public WebResponse list(@TQLContext UserContext userContext) {
    try {
        var list = Q.bookstores()
            .selectSelf()
            .page(1, 20)
            .comment("list tasks")
            .purpose("render dashboard list")
            .executeForList(userContext);
        return WebResponse.of(list);
    } catch (Exception e) {
        return WebResponse.fail(e.getMessage());
    }
}
```

## Create

```java
var entity = new Bookstore();
// Fill fields with generated updateXxx(...) methods, not setXxx(...).
entity.auditAs("Create new item").save(userContext);
```

## Update

```java
var entity = Q.bookstores()
    .filterById(id)
    .selectSelf()
    .comment("load for update")
    .purpose("edit entity")
    .executeForOne(userContext);

// Use updateXxx(...) methods for state changes.
// entity.updateName("new value");
entity.auditAs("Update entity properties").save(userContext);
```

## Load Relations

Use generated selectors. Do not write a loop that queries children one row at a time. The examples below focus on the entities with the highest reverse relation counts because they are stronger aggregate-root candidates.

```java
var list = Q.bookstores()
    .selectBookListWith(Q.books().selectSelf())
    .comment("load with bookList")
    .purpose("fetch child bookList")
    .executeForList(userContext);
```

```java
var list = Q.bookstores()
    .selectBookCategoryListWith(Q.bookCategories().selectSelf())
    .comment("load with bookCategoryList")
    .purpose("fetch child bookCategoryList")
    .executeForList(userContext);
```

```java
var list = Q.bookCategories()
    .selectBookstoreWith(Q.bookstores().selectSelf())
    .comment("load with bookstore")
    .purpose("fetch associated bookstore")
    .executeForList(userContext);
```

```java
var list = Q.bookCategories()
    .selectBookListWith(Q.books().selectSelf())
    .comment("load with bookList")
    .purpose("fetch child bookList")
    .executeForList(userContext);
```


## Delete

Use the generated TeaQL soft-delete API available on the entity/request class in this domain. If unsure, inspect the generated request class for the target entity and use the soft-delete operation it exposes.

Do not hard-delete rows. Do not write SQL `DELETE` or `UPDATE` statements. If the soft-delete API is not visible, stop and report that blocker instead of changing data through SQL.

## Common Mistakes

- Do not instantiate repositories directly in workspace business code.
- Do not use SQL for any database operation.
- Do not use deprecated `setXxx(...)` methods for updates. Use `updateXxx(...)`.
- Do not return raw entities or lists from controller query methods. Return `WebResponse.of(entity)` or `WebResponse.of(list)`.
- Do not forget `.executeForOne(userContext)` or `.executeForList(userContext)`.
- Do not forget `.comment("...")` and `.purpose("...")` on queries.
- Do not forget `.auditAs("...")` before calling `.save(ctx)` on entities.
- Do not assume relations are loaded unless the query selected them.
- Do not bypass `UserContext`; context carries logging, tenant, security, and repository resolution behavior.

## Entity Cheat Sheet

These entities are selected by reverse relation count, not by model declaration order.

- `Bookstore`: reverse relations `2`, query `Q.bookstores()`, save `new Bookstore().auditAs("comment").save(userContext)`, request `com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest`
- `BookCategory`: reverse relations `1`, query `Q.bookCategories()`, save `new BookCategory().auditAs("comment").save(userContext)`, request `com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest`