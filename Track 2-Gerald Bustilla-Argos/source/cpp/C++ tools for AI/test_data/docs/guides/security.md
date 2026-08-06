# Security Guide

## Authentication
All API endpoints require JWT authentication except /api/auth/login.
Tokens expire after 1 hour. Use refresh tokens to maintain sessions.

## Vulnerabilities
- SQL injection: Use parameterized queries
- XSS: Escape all user input in HTML output
- CSRF: Validate Origin header for state-changing operations
