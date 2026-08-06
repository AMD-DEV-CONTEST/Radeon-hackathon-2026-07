package com.doublechaintech.onlinebookstoreservice.book;

import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryExpression;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreExpression;
import io.teaql.core.UserContext;
import io.teaql.core.value.BaseEntityExpression;
import io.teaql.core.value.Expression;
import io.teaql.core.value.ExpressionAdaptor;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.function.Function;

public class BookExpression<T, E, U extends Book> extends ExpressionAdaptor<T, E, U> implements BaseEntityExpression<T, U> {
    public BookExpression(Expression<T, U> expression){
        super(expression);
    }

    public BookExpression(Expression<T, E> expression, Function<E, U> function){
        super(expression, function);
    }

     public BookExpression<T, U, U> updateId(Long id){
        return new BookExpression(this, $it -> {((Book)$it).__internalSet("id", id); return this;});
     }

     public BookExpression<T, U, U> save(UserContext userContext){
        return new BookExpression(this, $it -> ((Book)$it).auditAs("Saved by Expression").save(userContext));
     }

     public BookExpression<T, U, U> save(String intent, UserContext userContext){
        return new BookExpression(this, $it -> ((Book)$it).auditAs(intent).save(userContext));
     }

     public boolean isNull() {
        return resolve() == null;
     }


    public Expression<T, String> getTitle(){
       return apply(Book::getTitle);
    }
    public BookExpression<T, U, U> updateTitle(String title){
       return new BookExpression(this, $it ->  ((Book)$it).updateTitle(title));
    }

    public Expression<T, String> getAuthor(){
       return apply(Book::getAuthor);
    }
    public BookExpression<T, U, U> updateAuthor(String author){
       return new BookExpression(this, $it ->  ((Book)$it).updateAuthor(author));
    }

    public Expression<T, String> getIsbn(){
       return apply(Book::getIsbn);
    }
    public BookExpression<T, U, U> updateIsbn(String isbn){
       return new BookExpression(this, $it ->  ((Book)$it).updateIsbn(isbn));
    }

    public Expression<T, BigDecimal> getPrice(){
       return apply(Book::getPrice);
    }
    public BookExpression<T, U, U> updatePrice(BigDecimal price){
       return new BookExpression(this, $it ->  ((Book)$it).updatePrice(price));
    }

    public Expression<T, Integer> getStockCount(){
       return apply(Book::getStockCount);
    }
    public BookExpression<T, U, U> updateStockCount(Integer stockCount){
       return new BookExpression(this, $it ->  ((Book)$it).updateStockCount(stockCount));
    }

    public Expression<T, LocalDateTime> getCreateTime(){
       return apply(Book::getCreateTime);
    }
    public BookExpression<T, U, U> updateCreateTime(LocalDateTime createTime){
       return new BookExpression(this, $it ->  ((Book)$it).updateCreateTime(createTime));
    }

    public Expression<T, LocalDateTime> getUpdateTime(){
       return apply(Book::getUpdateTime);
    }
    public BookExpression<T, U, U> updateUpdateTime(LocalDateTime updateTime){
       return new BookExpression(this, $it ->  ((Book)$it).updateUpdateTime(updateTime));
    }

    public BookstoreExpression<T, U, Bookstore> getBookstore(){
       return new BookstoreExpression(this, $it ->  ((Book)$it).getBookstore());
    }

    public BookExpression<T, U, U> updateBookstore(Bookstore bookstore){
       return new BookExpression(this, $it ->  ((Book)$it).updateBookstore(bookstore));
    }

    public BookCategoryExpression<T, U, BookCategory> getCategory(){
       return new BookCategoryExpression(this, $it ->  ((Book)$it).getCategory());
    }

    public BookExpression<T, U, U> updateCategoryToFiction(){
       return new BookExpression(this, $it ->  ((Book)$it).updateCategoryToFiction());
    }
    public BookExpression<T, U, U> updateCategoryToNonFiction(){
       return new BookExpression(this, $it ->  ((Book)$it).updateCategoryToNonFiction());
    }
    public BookExpression<T, U, U> updateCategoryToScience(){
       return new BookExpression(this, $it ->  ((Book)$it).updateCategoryToScience());
    }
    public BookExpression<T, U, U> updateCategoryToHistory(){
       return new BookExpression(this, $it ->  ((Book)$it).updateCategoryToHistory());
    }

}