package com.doublechaintech.onlinebookstoreservice.book;

import io.teaql.core.SmartList;
import io.teaql.core.value.Expression;
import io.teaql.core.value.SmartListExpression;
import java.util.function.Function;

public class BookListExpression<T, E, U extends Book> extends SmartListExpression<T, E, U> {
    public BookListExpression(Expression<T, SmartList<U>> expression){
        super(expression);
    }

    public BookListExpression(Expression<T, E> expression, Function<E, SmartList<U>> function){
        super(expression, function);
    }

    public BookExpression<T, U, U> first() {
       return new BookExpression(super.first());
    }

    public BookExpression<T, U, U> get(int index) {
      return new BookExpression(super.get(index));
    }
}