// Authentication login handler
#include "auth_service.h"

void LoginHandler::handle(const Request& req, Response& res) {
    std::string username = req.get_param("username");
    std::string password = req.get_param("password");
    
    if (auth_service.authenticate(username, password)) {
        std::string token = token_handler.generate_token(username);
        session_manager.create_session(token, username);
        res.set_cookie("auth_token", token);
        res.json({{"status", "success"}, {"token", token}});
    } else {
        res.status(401).json({{"error", "authentication failed"}});
    }
}
