package com.doublechaintech.onlinebookstoreservice.bookcategory;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookChecker;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreChecker;
import io.teaql.core.UserContext;
import io.teaql.core.checker.Checker;
import io.teaql.core.checker.ObjectLocation;

public class BookCategoryChecker implements Checker<BookCategory>{

    public String type(){
        return BookCategory.INTERNAL_TYPE;
    }

    public void checkAndFix(UserContext _ctx, BookCategory bookCategory, ObjectLocation _parentLocation){
        if(needCheck(_ctx, bookCategory)){
            markAsChecked(_ctx, bookCategory);
            doCheck(_ctx, bookCategory, _parentLocation);
        }
    }

    public void doCheck(UserContext _ctx, BookCategory bookCategory, ObjectLocation _parentLocation){
      if((bookCategory == null)){
         return;
      }
      if(bookCategory.newItem()){
      }else if(bookCategory.updateItem()){
      }
      checkName(_ctx, bookCategory.getProperty(BookCategory.NAME_PROPERTY), newLocation(_parentLocation, BookCategory.NAME_PROPERTY));
      checkCode(_ctx, bookCategory.getProperty(BookCategory.CODE_PROPERTY), newLocation(_parentLocation, BookCategory.CODE_PROPERTY));
      checkBookstore(_ctx, bookCategory.getProperty(BookCategory.BOOKSTORE_PROPERTY), newLocation(_parentLocation, BookCategory.BOOKSTORE_PROPERTY));
      for(int i = 0; bookCategory.getBookList() != null && i < bookCategory.getBookList().size(); i++){
         Book book = bookCategory.getBookList().get(i);
         new BookChecker().checkAndFix(_ctx, book, newLocation(_parentLocation, BookCategory.BOOK_LIST_PROPERTY, i));
      }
    }

    public void checkName(UserContext _ctx, String name, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, name);
    if((name == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, name);

    }
    public void checkCode(UserContext _ctx, String code, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, code);
    if((code == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, code);

    }
    public void checkBookstore(UserContext _ctx, Bookstore bookstore, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, bookstore);
    if((bookstore == null)){
        return;
    }
    new BookstoreChecker().checkAndFix(_ctx, bookstore, _parentLocation);
    }
}