package com.doublechaintech.onlinebookstoreservice.bookcategory;

import io.teaql.core.SmartList;
import io.teaql.core.value.Expression;
import io.teaql.core.value.SmartListExpression;
import java.util.function.Function;

public class BookCategoryListExpression<T, E, U extends BookCategory> extends SmartListExpression<T, E, U> {
    public BookCategoryListExpression(Expression<T, SmartList<U>> expression){
        super(expression);
    }

    public BookCategoryListExpression(Expression<T, E> expression, Function<E, SmartList<U>> function){
        super(expression, function);
    }

    public BookCategoryExpression<T, U, U> first() {
       return new BookCategoryExpression(super.first());
    }

    public BookCategoryExpression<T, U, U> get(int index) {
      return new BookCategoryExpression(super.get(index));
    }
}