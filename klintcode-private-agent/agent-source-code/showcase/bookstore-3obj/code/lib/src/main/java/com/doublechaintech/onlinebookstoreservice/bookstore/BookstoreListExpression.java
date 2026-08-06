package com.doublechaintech.onlinebookstoreservice.bookstore;

import io.teaql.core.SmartList;
import io.teaql.core.value.Expression;
import io.teaql.core.value.SmartListExpression;
import java.util.function.Function;

public class BookstoreListExpression<T, E, U extends Bookstore> extends SmartListExpression<T, E, U> {
    public BookstoreListExpression(Expression<T, SmartList<U>> expression){
        super(expression);
    }

    public BookstoreListExpression(Expression<T, E> expression, Function<E, SmartList<U>> function){
        super(expression, function);
    }

    public BookstoreExpression<T, U, U> first() {
       return new BookstoreExpression(super.first());
    }

    public BookstoreExpression<T, U, U> get(int index) {
      return new BookstoreExpression(super.get(index));
    }
}