import { buildQuery, get, post, put } from "./client.js";

export function getStats() {
  return get("/stats");
}

export function getTimeline(era) {
  return get("/timeline", era ? { era } : {});
}

export function getActiveDatabase() {
  return get("/databases/active");
}

export function getDatabases() {
  return get("/databases");
}

export function getActiveBook() {
  return get("/books/active");
}

export function getBooks(databaseId = null) {
  return get("/books", { database_id: databaseId });
}

export function createDatabase({ name, author = "", description = "" }) {
  return post(`/databases${buildQuery({ name, author, description })}`, {});
}

export function initializeDatabase(databaseId) {
  return post(`/databases/${databaseId}/init-db`, {});
}

export function activateDatabase(databaseId) {
  return post(`/databases/${databaseId}/activate`, {});
}

export function createBook({ bookId, title, databaseId }) {
  return post(`/books${buildQuery({ book_id: bookId, title, database_id: databaseId })}`, {});
}

export function updateBook(bookId, { title, description, author, databaseId }) {
  return put(`/books/${bookId}${buildQuery({ title, description, author, database_id: databaseId })}`, {});
}

export function activateBook(bookId) {
  return post(`/books/activate${buildQuery({ book_id: bookId })}`, {});
}
