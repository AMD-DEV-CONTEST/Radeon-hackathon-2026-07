# Authentication API

## Overview
The authentication system provides secure login, token generation, and session management.

## Endpoints
- `POST /api/auth/login` - Login with username and password
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/refresh` - Refresh authentication token
- `POST /api/auth/logout` - Logout and invalidate session

## Token Format
Tokens are JWT formatted with HS256 signing. Claims include username and expiration.
