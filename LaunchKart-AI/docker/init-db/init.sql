-- LaunchKart AI 2.0 — Database Initialization
-- This script runs when PostgreSQL container starts for the first time

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create application schema
-- (Tables will be created by Alembic migrations, but we ensure the DB is ready)

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE launchkart_db TO launchkart;

