#include <cassert>
#include "connection_pool.h"

void test_connection_pool() {
    ConnectionPool pool(5, "postgresql://localhost/db");
    auto conn = pool.acquire();
    assert(conn.is_valid());
    pool.release(conn);
}

void test_query_builder() {
    QueryBuilder qb("users");
    auto query = qb.select("*").where("age > 18").order_by("name").build();
    assert(query.find("SELECT") != std::string::npos);
    assert(query.find("WHERE") != std::string::npos);
}
