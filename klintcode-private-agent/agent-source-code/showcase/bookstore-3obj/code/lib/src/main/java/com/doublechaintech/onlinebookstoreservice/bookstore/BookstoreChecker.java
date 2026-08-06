package com.doublechaintech.onlinebookstoreservice.bookstore;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookChecker;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryChecker;
import io.teaql.core.UserContext;
import io.teaql.core.checker.Checker;
import io.teaql.core.checker.ObjectLocation;
import java.time.LocalDateTime;

public class BookstoreChecker implements Checker<Bookstore>{

    public String type(){
        return Bookstore.INTERNAL_TYPE;
    }

    public void checkAndFix(UserContext _ctx, Bookstore bookstore, ObjectLocation _parentLocation){
        if(needCheck(_ctx, bookstore)){
            markAsChecked(_ctx, bookstore);
            doCheck(_ctx, bookstore, _parentLocation);
        }
    }

    public void doCheck(UserContext _ctx, Bookstore bookstore, ObjectLocation _parentLocation){
      if((bookstore == null)){
         return;
      }
      if(bookstore.newItem()){
        if(bookstore.getCreateTime() == null){
           bookstore.updateCreateTime(java.time.LocalDateTime.now());
        }if(bookstore.getUpdateTime() == null){
           bookstore.updateUpdateTime(java.time.LocalDateTime.now());
        }
      }else if(bookstore.updateItem()){
        bookstore.updateUpdateTime(java.time.LocalDateTime.now());
      }
      checkName(_ctx, bookstore.getProperty(Bookstore.NAME_PROPERTY), newLocation(_parentLocation, Bookstore.NAME_PROPERTY));
      checkAddress(_ctx, bookstore.getProperty(Bookstore.ADDRESS_PROPERTY), newLocation(_parentLocation, Bookstore.ADDRESS_PROPERTY));
      checkPhone(_ctx, bookstore.getProperty(Bookstore.PHONE_PROPERTY), newLocation(_parentLocation, Bookstore.PHONE_PROPERTY));
      checkCreateTime(_ctx, bookstore.getProperty(Bookstore.CREATE_TIME_PROPERTY), newLocation(_parentLocation, Bookstore.CREATE_TIME_PROPERTY));
      checkUpdateTime(_ctx, bookstore.getProperty(Bookstore.UPDATE_TIME_PROPERTY), newLocation(_parentLocation, Bookstore.UPDATE_TIME_PROPERTY));
      for(int i = 0; bookstore.getBookList() != null && i < bookstore.getBookList().size(); i++){
         Book book = bookstore.getBookList().get(i);
         new BookChecker().checkAndFix(_ctx, book, newLocation(_parentLocation, Bookstore.BOOK_LIST_PROPERTY, i));
      }
      for(int i = 0; bookstore.getBookCategoryList() != null && i < bookstore.getBookCategoryList().size(); i++){
         BookCategory bookCategory = bookstore.getBookCategoryList().get(i);
         new BookCategoryChecker().checkAndFix(_ctx, bookCategory, newLocation(_parentLocation, Bookstore.BOOK_CATEGORY_LIST_PROPERTY, i));
      }
    }

    public void checkName(UserContext _ctx, String name, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, name);
    if((name == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, name);

    }
    public void checkAddress(UserContext _ctx, String address, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, address);
    if((address == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, address);

    }
    public void checkPhone(UserContext _ctx, Integer phone, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, phone);
    if((phone == null)){
        return;
    }
    }
    public void checkCreateTime(UserContext _ctx, LocalDateTime createTime, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, createTime);
    if((createTime == null)){
        return;
    }
    }
    public void checkUpdateTime(UserContext _ctx, LocalDateTime updateTime, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, updateTime);
    if((updateTime == null)){
        return;
    }
    }
}