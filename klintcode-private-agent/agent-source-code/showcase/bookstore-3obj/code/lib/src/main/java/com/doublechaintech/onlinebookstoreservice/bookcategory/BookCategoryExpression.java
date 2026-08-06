package com.doublechaintech.onlinebookstoreservice.bookcategory;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookListExpression;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreExpression;
import io.teaql.core.UserContext;
import io.teaql.core.value.BaseEntityExpression;
import io.teaql.core.value.Expression;
import io.teaql.core.value.ExpressionAdaptor;
import java.util.function.Function;

public class BookCategoryExpression<T, E, U extends BookCategory> extends ExpressionAdaptor<T, E, U> implements BaseEntityExpression<T, U> {
    public BookCategoryExpression(Expression<T, U> expression){
        super(expression);
    }

    public BookCategoryExpression(Expression<T, E> expression, Function<E, U> function){
        super(expression, function);
    }

     public BookCategoryExpression<T, U, U> updateId(Long id){
        return new BookCategoryExpression(this, $it -> {((BookCategory)$it).__internalSet("id", id); return this;});
     }

     public BookCategoryExpression<T, U, U> save(UserContext userContext){
        return new BookCategoryExpression(this, $it -> ((BookCategory)$it).auditAs("Saved by Expression").save(userContext));
     }

     public BookCategoryExpression<T, U, U> save(String intent, UserContext userContext){
        return new BookCategoryExpression(this, $it -> ((BookCategory)$it).auditAs(intent).save(userContext));
     }

     public boolean isNull() {
        return resolve() == null;
     }


    public Expression<T, String> getName(){
       return apply(BookCategory::getName);
    }
    public BookCategoryExpression<T, U, U> updateName(String name){
       return new BookCategoryExpression(this, $it ->  ((BookCategory)$it).updateName(name));
    }

    public Expression<T, String> getCode(){
       return apply(BookCategory::getCode);
    }
    public BookCategoryExpression<T, U, U> updateCode(String code){
       return new BookCategoryExpression(this, $it ->  ((BookCategory)$it).updateCode(code));
    }

    public BookstoreExpression<T, U, Bookstore> getBookstore(){
       return new BookstoreExpression(this, $it ->  ((BookCategory)$it).getBookstore());
    }

    public BookCategoryExpression<T, U, U> updateBookstore(Bookstore bookstore){
       return new BookCategoryExpression(this, $it ->  ((BookCategory)$it).updateBookstore(bookstore));
    }

    public BookListExpression<T, U, Book> getBookList(){
        return new BookListExpression(this, $it ->  ((BookCategory)$it).getBookList());
    }
    public BookCategoryExpression<T, U, U> addBook(Book book){
       return new BookCategoryExpression(this, $it ->  ((BookCategory)$it).addBook(book));
    }
}