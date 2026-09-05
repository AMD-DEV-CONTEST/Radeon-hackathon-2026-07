// Database migration handler
#include "migration_handler.h"

void MigrationHandler::run_migrations() {
    auto files = scan_migration_directory("migrations/");
    for (const auto& file : files) {
        std::string sql = read_file(file);
        database.execute(sql);
        record_migration(file);
    }
}
