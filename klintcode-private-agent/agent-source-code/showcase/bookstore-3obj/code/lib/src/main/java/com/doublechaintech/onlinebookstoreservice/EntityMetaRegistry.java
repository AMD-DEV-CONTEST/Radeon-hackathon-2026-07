package com.doublechaintech.onlinebookstoreservice;

import io.teaql.core.meta.EntityDescriptor;
import io.teaql.core.meta.EntityMetaAssembler;
import io.teaql.core.meta.EntityMetaFactory;
import io.teaql.core.meta.PropertyDescriptor;
import java.math.BigDecimal;
import java.time.LocalDateTime;

public class EntityMetaRegistry implements EntityMetaAssembler {
  private EntityMetaFactory $factory;

  @Override
  public void assemble(EntityMetaFactory factory) {
    this.$factory = factory;
    registerBookstore();
    registerBookCategory();
    registerBook();
  }
  private void registerBookstore() {
      EntityDescriptor entityDescriptor = new EntityDescriptor();
      entityDescriptor.setType(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.INTERNAL_TYPE);
      entityDescriptor.setTargetType(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.class);
      entityDescriptor.setEntitySupplier(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore::new);
      entityDescriptor.with("name", "Bookstore")
      .with("module", "Core")
      .with("module_key", "core");

      PropertyDescriptor id = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.ID_PROPERTY, Long.class)
      ;
      PropertyDescriptor name = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.NAME_PROPERTY, String.class)
      ;
      PropertyDescriptor address = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.ADDRESS_PROPERTY, String.class)
      ;
      PropertyDescriptor phone = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.PHONE_PROPERTY, Integer.class)
      ;
      PropertyDescriptor createTime = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.CREATE_TIME_PROPERTY, LocalDateTime.class)
      ;
      PropertyDescriptor updateTime = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.UPDATE_TIME_PROPERTY, LocalDateTime.class)
      ;
      PropertyDescriptor version = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.VERSION_PROPERTY, Long.class)
      ;
      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.ID_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("sqlType", "BIGINT")
      .with("isId", "true")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.NAME_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("candidates", "City Books")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.ADDRESS_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("candidates", "123 Main St")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.PHONE_PROPERTY).with("isPassword", "false")
      .with("db2_sqlType", "decimal(19,7)")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(19,7)")
      .with("javaType", "java.lang.Integer")
      .with("candidates", "13800138000")
      .with("sqlType", "INTEGER")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "true")
      .with("isInt", "true")
      .with("isString", "false")
      .with("isDate", "false")
      .with("graphqlType", "Int")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.CREATE_TIME_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("javaType", "java.time.LocalDateTime")
      .with("candidates", "createTime()")
      .with("sqlType", "TIMESTAMP")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("mssql_sqlType", "dateTime")
      .with("isDateTime", "true")
      .with("createFunction", "now")
      .with("isDate", "true")
      .with("isString", "false")
      .with("graphqlType", "LocalTime")
      .with("isTime", "true")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.UPDATE_TIME_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("updateFunction", "now")
      .with("javaType", "java.time.LocalDateTime")
      .with("candidates", "updateTime()")
      .with("sqlType", "TIMESTAMP")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("mssql_sqlType", "dateTime")
      .with("isDateTime", "true")
      .with("createFunction", "now")
      .with("isDate", "true")
      .with("isString", "false")
      .with("graphqlType", "LocalTime")
      .with("isTime", "true")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.VERSION_PROPERTY).with("isPassword", "false")
      .with("isVersion", "true")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("sqlType", "BIGINT")
      .with("isId", "false")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      $factory.register(entityDescriptor);
  }
  private void registerBook() {
      EntityDescriptor entityDescriptor = new EntityDescriptor();
      entityDescriptor.setType(com.doublechaintech.onlinebookstoreservice.book.Book.INTERNAL_TYPE);
      entityDescriptor.setTargetType(com.doublechaintech.onlinebookstoreservice.book.Book.class);
      entityDescriptor.setEntitySupplier(com.doublechaintech.onlinebookstoreservice.book.Book::new);
      entityDescriptor.with("name", "Book")
      .with("module", "Core")
      .with("module_key", "core");

      PropertyDescriptor id = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.ID_PROPERTY, Long.class)
      ;
      PropertyDescriptor title = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.TITLE_PROPERTY, String.class)
      ;
      PropertyDescriptor author = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.AUTHOR_PROPERTY, String.class)
      ;
      PropertyDescriptor isbn = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.ISBN_PROPERTY, String.class)
      ;
      PropertyDescriptor price = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.PRICE_PROPERTY, BigDecimal.class)
      ;
      PropertyDescriptor stockCount = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.STOCK_COUNT_PROPERTY, Integer.class)
      ;
      PropertyDescriptor createTime = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.CREATE_TIME_PROPERTY, LocalDateTime.class)
      ;
      PropertyDescriptor updateTime = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.UPDATE_TIME_PROPERTY, LocalDateTime.class)
      ;
      PropertyDescriptor bookstore = 
      entityDescriptor.addObjectProperty($factory, com.doublechaintech.onlinebookstoreservice.book.Book.BOOKSTORE_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.INTERNAL_TYPE, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.BOOK_LIST_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.class)
      ;
      PropertyDescriptor category = 
      entityDescriptor.addObjectProperty($factory, com.doublechaintech.onlinebookstoreservice.book.Book.CATEGORY_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.INTERNAL_TYPE, com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.BOOK_LIST_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.class)
      ;
      PropertyDescriptor version = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.book.Book.VERSION_PROPERTY, Long.class)
      ;
      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.ID_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("sqlType", "BIGINT")
      .with("isId", "true")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.TITLE_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.AUTHOR_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.ISBN_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.PRICE_PROPERTY).with("isPassword", "false")
      .with("db2_sqlType", "decimal(19,7)")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(19,7)")
      .with("javaType", "java.math.BigDecimal")
      .with("sqlType", "NUMERIC(19,7)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "true")
      .with("isString", "false")
      .with("isDate", "false")
      .with("graphqlType", "BigDecimal")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.STOCK_COUNT_PROPERTY).with("isPassword", "false")
      .with("db2_sqlType", "decimal(19,7)")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(19,7)")
      .with("javaType", "java.lang.Integer")
      .with("sqlType", "INTEGER")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "true")
      .with("isInt", "true")
      .with("isString", "false")
      .with("isDate", "false")
      .with("graphqlType", "Int")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.CREATE_TIME_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("javaType", "java.time.LocalDateTime")
      .with("sqlType", "TIMESTAMP")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("mssql_sqlType", "dateTime")
      .with("isDateTime", "true")
      .with("createFunction", "now")
      .with("isDate", "true")
      .with("isString", "false")
      .with("graphqlType", "LocalTime")
      .with("isTime", "true")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.UPDATE_TIME_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("updateFunction", "now")
      .with("javaType", "java.time.LocalDateTime")
      .with("sqlType", "TIMESTAMP")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("mssql_sqlType", "dateTime")
      .with("isDateTime", "true")
      .with("createFunction", "now")
      .with("isDate", "true")
      .with("isString", "false")
      .with("graphqlType", "LocalTime")
      .with("isTime", "true")
      .with("isText", "false");



      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.book.Book.VERSION_PROPERTY).with("isPassword", "false")
      .with("isVersion", "true")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("sqlType", "BIGINT")
      .with("isId", "false")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      $factory.register(entityDescriptor);
  }
  private void registerBookCategory() {
      EntityDescriptor entityDescriptor = new EntityDescriptor();
      entityDescriptor.setType(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.INTERNAL_TYPE);
      entityDescriptor.setTargetType(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.class);
      entityDescriptor.setEntitySupplier(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory::new);
      entityDescriptor.with("name", "Book Category")
      .with("module", "Core")
      .with("module_key", "core")
      .with("constant", "true")
      .with("identifier", "code");

      PropertyDescriptor id = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.ID_PROPERTY, Long.class)
      ;
      PropertyDescriptor name = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.NAME_PROPERTY, String.class)
      ;
      PropertyDescriptor code = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.CODE_PROPERTY, String.class)
      ;
      PropertyDescriptor bookstore = 
      entityDescriptor.addObjectProperty($factory, com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.BOOKSTORE_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.INTERNAL_TYPE, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.BOOK_CATEGORY_LIST_PROPERTY, com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.class)
      ;
      PropertyDescriptor version = 
      entityDescriptor.addSimpleProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.VERSION_PROPERTY, Long.class)
      ;
      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.ID_PROPERTY).with("isPassword", "false")
      .with("isVersion", "false")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("candidates", "1001,1002,1003,1004")
      .with("sqlType", "BIGINT")
      .with("isId", "true")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.NAME_PROPERTY).with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("candidates", "Fiction,Non-Fiction,Science,History")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.CODE_PROPERTY).with("identifier", "true")
      .with("isPassword", "false")
      .with("max", "100")
      .with("isVersion", "false")
      .with("javaType", "java.lang.String")
      .with("candidates", "FICTION,NON_FICTION,SCIENCE,HISTORY")
      .with("sqlType", "VARCHAR(<max>)")
      .with("isId", "false")
      .with("isBool", "false")
      .with("isBaseEntityField", "false")
      .with("isNumber", "false")
      .with("isString", "true")
      .with("isDate", "false")
      .with("graphqlType", "String")
      .with("isTime", "false")
      .with("isText", "false");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.BOOKSTORE_PROPERTY).with("candidates", "bookstore()");

      entityDescriptor.findProperty(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.VERSION_PROPERTY).with("isPassword", "false")
      .with("isVersion", "true")
      .with("oracle_sqlType", "number(11)")
      .with("javaType", "java.lang.Long")
      .with("sqlType", "BIGINT")
      .with("isId", "false")
      .with("isBaseEntityField", "true")
      .with("isBool", "false")
      .with("isNumber", "false")
      .with("isString", "false")
      .with("isDate", "false")
      .with("snowflake_sqlType", "number")
      .with("graphqlType", "Long")
      .with("isTime", "false")
      .with("isText", "false");

      $factory.register(entityDescriptor);
  }
}