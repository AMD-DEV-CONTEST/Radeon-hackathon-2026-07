package com.doublechaintech.onlinebookstoreservice.book;

import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryChecker;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreChecker;
import io.teaql.core.UserContext;
import io.teaql.core.checker.Checker;
import io.teaql.core.checker.ObjectLocation;
import java.math.BigDecimal;
import java.time.LocalDateTime;

public class BookChecker implements Checker<Book>{

    public String type(){
        return Book.INTERNAL_TYPE;
    }

    public void checkAndFix(UserContext _ctx, Book book, ObjectLocation _parentLocation){
        if(needCheck(_ctx, book)){
            markAsChecked(_ctx, book);
            doCheck(_ctx, book, _parentLocation);
        }
    }

    public void doCheck(UserContext _ctx, Book book, ObjectLocation _parentLocation){
      if((book == null)){
         return;
      }
      if(book.newItem()){
        if(book.getCreateTime() == null){
           book.updateCreateTime(java.time.LocalDateTime.now());
        }if(book.getUpdateTime() == null){
           book.updateUpdateTime(java.time.LocalDateTime.now());
        }
      }else if(book.updateItem()){
        book.updateUpdateTime(java.time.LocalDateTime.now());
      }
      checkTitle(_ctx, book.getProperty(Book.TITLE_PROPERTY), newLocation(_parentLocation, Book.TITLE_PROPERTY));
      checkAuthor(_ctx, book.getProperty(Book.AUTHOR_PROPERTY), newLocation(_parentLocation, Book.AUTHOR_PROPERTY));
      checkIsbn(_ctx, book.getProperty(Book.ISBN_PROPERTY), newLocation(_parentLocation, Book.ISBN_PROPERTY));
      checkPrice(_ctx, book.getProperty(Book.PRICE_PROPERTY), newLocation(_parentLocation, Book.PRICE_PROPERTY));
      checkStockCount(_ctx, book.getProperty(Book.STOCK_COUNT_PROPERTY), newLocation(_parentLocation, Book.STOCK_COUNT_PROPERTY));
      checkCreateTime(_ctx, book.getProperty(Book.CREATE_TIME_PROPERTY), newLocation(_parentLocation, Book.CREATE_TIME_PROPERTY));
      checkUpdateTime(_ctx, book.getProperty(Book.UPDATE_TIME_PROPERTY), newLocation(_parentLocation, Book.UPDATE_TIME_PROPERTY));
      checkBookstore(_ctx, book.getProperty(Book.BOOKSTORE_PROPERTY), newLocation(_parentLocation, Book.BOOKSTORE_PROPERTY));
      checkCategory(_ctx, book.getProperty(Book.CATEGORY_PROPERTY), newLocation(_parentLocation, Book.CATEGORY_PROPERTY));
    }

    public void checkTitle(UserContext _ctx, String title, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, title);
    if((title == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, title);

    }
    public void checkAuthor(UserContext _ctx, String author, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, author);
    if((author == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, author);

    }
    public void checkIsbn(UserContext _ctx, String isbn, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, isbn);
    if((isbn == null)){
        return;
    }
    maxStringCheck(_ctx, _parentLocation, 100, isbn);

    }
    public void checkPrice(UserContext _ctx, BigDecimal price, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, price);
    if((price == null)){
        return;
    }
    }
    public void checkStockCount(UserContext _ctx, Integer stockCount, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, stockCount);
    if((stockCount == null)){
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
    public void checkBookstore(UserContext _ctx, Bookstore bookstore, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, bookstore);
    if((bookstore == null)){
        return;
    }
    new BookstoreChecker().checkAndFix(_ctx, bookstore, _parentLocation);
    }
    public void checkCategory(UserContext _ctx, BookCategory category, ObjectLocation _parentLocation){
    requiredCheck(_ctx, _parentLocation, category);
    if((category == null)){
        return;
    }
    new BookCategoryChecker().checkAndFix(_ctx, category, _parentLocation);
    }
}