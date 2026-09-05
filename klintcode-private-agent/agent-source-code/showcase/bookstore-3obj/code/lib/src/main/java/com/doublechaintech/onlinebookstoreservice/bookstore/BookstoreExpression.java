package com.doublechaintech.onlinebookstoreservice.bookstore;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookListExpression;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryListExpression;
import io.teaql.core.UserContext;
import io.teaql.core.value.BaseEntityExpression;
import io.teaql.core.value.Expression;
import io.teaql.core.value.ExpressionAdaptor;
import java.time.LocalDateTime;
import java.util.function.Function;

public class BookstoreExpression<T, E, U extends Bookstore> extends ExpressionAdaptor<T, E, U> implements BaseEntityExpression<T, U> {
    public BookstoreExpression(Expression<T, U> expression){
        super(expression);
    }

    public BookstoreExpression(Expression<T, E> expression, Function<E, U> function){
        super(expression, function);
    }

     public BookstoreExpression<T, U, U> updateId(Long id){
        return new BookstoreExpression(this, $it -> {((Bookstore)$it).__internalSet("id", id); return this;});
     }

     public BookstoreExpression<T, U, U> save(UserContext userContext){
        return new BookstoreExpression(this, $it -> ((Bookstore)$it).auditAs("Saved by Expression").save(userContext));
     }

     public BookstoreExpression<T, U, U> save(String intent, UserContext userContext){
        return new BookstoreExpression(this, $it -> ((Bookstore)$it).auditAs(intent).save(userContext));
     }

     public boolean isNull() {
        return resolve() == null;
     }


    public Expression<T, String> getName(){
       return apply(Bookstore::getName);
    }
    public BookstoreExpression<T, U, U> updateName(String name){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).updateName(name));
    }

    public Expression<T, String> getAddress(){
       return apply(Bookstore::getAddress);
    }
    public BookstoreExpression<T, U, U> updateAddress(String address){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).updateAddress(address));
    }

    public Expression<T, Integer> getPhone(){
       return apply(Bookstore::getPhone);
    }
    public BookstoreExpression<T, U, U> updatePhone(Integer phone){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).updatePhone(phone));
    }

    public Expression<T, LocalDateTime> getCreateTime(){
       return apply(Bookstore::getCreateTime);
    }
    public BookstoreExpression<T, U, U> updateCreateTime(LocalDateTime createTime){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).updateCreateTime(createTime));
    }

    public Expression<T, LocalDateTime> getUpdateTime(){
       return apply(Bookstore::getUpdateTime);
    }
    public BookstoreExpression<T, U, U> updateUpdateTime(LocalDateTime updateTime){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).updateUpdateTime(updateTime));
    }

    public BookListExpression<T, U, Book> getBookList(){
        return new BookListExpression(this, $it ->  ((Bookstore)$it).getBookList());
    }
    public BookCategoryListExpression<T, U, BookCategory> getBookCategoryList(){
        return new BookCategoryListExpression(this, $it ->  ((Bookstore)$it).getBookCategoryList());
    }
    public BookstoreExpression<T, U, U> addBook(Book book){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).addBook(book));
    }
    public BookstoreExpression<T, U, U> addBookCategory(BookCategory bookCategory){
       return new BookstoreExpression(this, $it ->  ((Bookstore)$it).addBookCategory(bookCategory));
    }
}