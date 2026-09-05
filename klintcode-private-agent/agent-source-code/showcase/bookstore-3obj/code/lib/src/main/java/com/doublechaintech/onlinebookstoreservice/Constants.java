package com.doublechaintech.onlinebookstoreservice;

import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;

public interface Constants  {
  public static final long BOOKSTORE_ID = 1l;
  public static final Bookstore BOOKSTORE = Bookstore.refer(BOOKSTORE_ID);
  public static final long BOOK_CATEGORY_FICTION_ID = 1001l ;
  public static final BookCategory BOOK_CATEGORY_FICTION = BookCategory.refer(BOOK_CATEGORY_FICTION_ID);public static final long BOOK_CATEGORY_NON_FICTION_ID = 1002l ;
  public static final BookCategory BOOK_CATEGORY_NON_FICTION = BookCategory.refer(BOOK_CATEGORY_NON_FICTION_ID);public static final long BOOK_CATEGORY_SCIENCE_ID = 1003l ;
  public static final BookCategory BOOK_CATEGORY_SCIENCE = BookCategory.refer(BOOK_CATEGORY_SCIENCE_ID);public static final long BOOK_CATEGORY_HISTORY_ID = 1004l ;
  public static final BookCategory BOOK_CATEGORY_HISTORY = BookCategory.refer(BOOK_CATEGORY_HISTORY_ID);
}