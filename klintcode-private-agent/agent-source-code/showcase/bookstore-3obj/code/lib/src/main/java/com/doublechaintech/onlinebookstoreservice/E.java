package com.doublechaintech.onlinebookstoreservice;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookExpression;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryExpression;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreExpression;
import io.teaql.core.value.ValueExpression;

public class E  {
  public static BookstoreExpression<Bookstore, Bookstore, Bookstore> bookstore(Bookstore bookstore){
      return new BookstoreExpression(new ValueExpression(bookstore));
  }
  public static BookExpression<Book, Book, Book> book(Book book){
      return new BookExpression(new ValueExpression(book));
  }
  public static BookCategoryExpression<BookCategory, BookCategory, BookCategory> bookCategory(BookCategory bookCategory){
      return new BookCategoryExpression(new ValueExpression(bookCategory));
  }
}