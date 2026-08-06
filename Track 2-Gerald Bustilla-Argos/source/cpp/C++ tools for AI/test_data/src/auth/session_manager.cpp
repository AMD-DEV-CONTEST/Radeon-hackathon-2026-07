// Session management with Redis cache
#include "session_manager.h"

void SessionManager::create_session(const std::string& token, const std::string& username) {
    Session session;
    session.token = token;
    session.username = username;
    session.created_at = std::time(nullptr);
    session.expires_at = session.created_at + 3600;
    
    cache.set("session:" + token, session.serialize(), 3600);
}

bool SessionManager::validate_session(const std::string& token) {
    auto data = cache.get("session:" + token);
    if (!data) return false;
    return true;
}
