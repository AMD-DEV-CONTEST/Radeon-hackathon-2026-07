// Database connection pool implementation
#include "connection_pool.h"

ConnectionPool::ConnectionPool(size_t max_connections, const std::string& conn_str)
    : max_connections_(max_connections), conn_str_(conn_str) {
    for (size_t i = 0; i < max_connections; i++) {
        connections_.push(create_connection());
    }
}

Connection ConnectionPool::acquire() {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return !connections_.empty(); });
    auto conn = connections_.front();
    connections_.pop();
    return conn;
}
