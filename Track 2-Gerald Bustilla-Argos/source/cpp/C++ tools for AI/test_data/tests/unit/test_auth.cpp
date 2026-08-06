#include <cassert>
#include "auth_service.h"

void test_authentication_success() {
    AuthService auth;
    auth.register_user("testuser", "password123");
    assert(auth.authenticate("testuser", "password123"));
}

void test_authentication_failure() {
    AuthService auth;
    assert(!auth.authenticate("nonexistent", "wrong"));
}

void test_token_generation() {
    TokenHandler handler;
    auto token = handler.generate_token("user");
    assert(!token.empty());
    assert(handler.validate_token(token));
}
