# REST API Documentation

## Authentication
### POST /api/auth/login
Request: `{"username": "admin", "password": "secret"}`
Response: `{"token": "jwt_token", "expires": 3600}`

## Search
### GET /api/search
Parameters: query (string), top_k (int, default 10)
Response: `{"total_hits": 5, "text_hits": [...]}`
