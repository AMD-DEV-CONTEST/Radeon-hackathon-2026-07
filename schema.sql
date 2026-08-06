-- SQL Schema for LibriAI (AI Library Assistant)
-- Creates the library database and the books inventory table

CREATE DATABASE IF NOT EXISTS library_db;
USE library_db;

DROP TABLE IF EXISTS books;

CREATE TABLE books (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    author VARCHAR(255) NOT NULL,
    category VARCHAR(255) NOT NULL,
    description TEXT,
    publisher VARCHAR(255) DEFAULT NULL,
    isbn VARCHAR(255) DEFAULT NULL UNIQUE,
    shelf_number VARCHAR(255) DEFAULT NULL,
    quantity INT NOT NULL CHECK (quantity >= 0),
    availability BOOLEAN NOT NULL DEFAULT TRUE,
    image_url VARCHAR(255) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Indexing for search performance on keyword fields
CREATE INDEX idx_books_search ON books(title, author, category);
