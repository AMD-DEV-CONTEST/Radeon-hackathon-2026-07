// JWT token handler for authentication
#include "token_handler.h"
#include <jwt/jwt.h>

std::string TokenHandler::generate_token(const std::string& username) {
    jwt::jwt_object obj{jwt::params::algorithm("HS256")};
    obj.add_claim("username", username);
    obj.add_claim("exp", std::time(nullptr) + 3600);
    obj.set_secret(config.get("jwt_secret"));
    return obj.signature();
}

bool TokenHandler::validate_token(const std::string& token) {
    try {
        auto decoded = jwt::decode(token, jwt::params::algorithm("HS256"));
        return true;
    } catch (...) {
        return false;
    }
}
