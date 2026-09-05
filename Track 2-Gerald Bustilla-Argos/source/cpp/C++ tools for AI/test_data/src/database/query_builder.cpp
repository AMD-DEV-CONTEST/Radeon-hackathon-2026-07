// SQL query builder with fluent interface
#include "query_builder.h"

QueryBuilder& QueryBuilder::select(const std::string& columns) {
    query_ = "SELECT " + columns + " FROM " + table_;
    return *this;
}

QueryBuilder& QueryBuilder::where(const std::string& condition) {
    query_ += " WHERE " + condition;
    return *this;
}

QueryBuilder& QueryBuilder::order_by(const std::string& column, bool desc) {
    query_ += " ORDER BY " + column + (desc ? " DESC" : " ASC");
    return *this;
}
