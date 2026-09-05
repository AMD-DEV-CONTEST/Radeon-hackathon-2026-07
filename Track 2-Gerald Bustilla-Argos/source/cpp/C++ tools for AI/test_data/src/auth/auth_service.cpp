// Authentication service implementation
#include "auth_service.h"
#include <bcrypt/bcrypt.h>

bool AuthService::authenticate(const std::string& username, const std::string& password) {
    auto user = database.find_user(username);
    if (!user) return false;
    
    return bcrypt::validate(password, user->password_hash);
}

bool AuthService::register_user(const std::string& username, const std::string& password) {
    std::string hash = bcrypt::generate(password);
    return database.insert_user(username, hash);
}
