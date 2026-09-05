package com.doublechaintech.onlinebookstoreservice;

import io.teaql.core.criteria.Operator;

public class Q  {
  public static com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest<com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore> bookstores(){
      return new com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.class).selectSelf().withVersion(Operator.GREATER_THAN, 0l);
  }
  public static com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest<com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore> bookstoresWithMinimalFields(){
      return new com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest(com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore.class).withVersion(Operator.GREATER_THAN, 0l);
  }


  public static com.doublechaintech.onlinebookstoreservice.book.BookRequest<com.doublechaintech.onlinebookstoreservice.book.Book> books(){
      return new com.doublechaintech.onlinebookstoreservice.book.BookRequest(com.doublechaintech.onlinebookstoreservice.book.Book.class).selectSelf().withVersion(Operator.GREATER_THAN, 0l);
  }
  public static com.doublechaintech.onlinebookstoreservice.book.BookRequest<com.doublechaintech.onlinebookstoreservice.book.Book> booksWithMinimalFields(){
      return new com.doublechaintech.onlinebookstoreservice.book.BookRequest(com.doublechaintech.onlinebookstoreservice.book.Book.class).withVersion(Operator.GREATER_THAN, 0l);
  }


  public static com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest<com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory> bookCategories(){
      return new com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.class).selectSelf().withVersion(Operator.GREATER_THAN, 0l);
  }
  public static com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest<com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory> bookCategoriesWithMinimalFields(){
      return new com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest(com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory.class).withVersion(Operator.GREATER_THAN, 0l);
  }


}