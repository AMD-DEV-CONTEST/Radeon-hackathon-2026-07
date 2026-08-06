import { get, post } from "./client.js";

export function searchByKeyword(query) {
  return post("/search", query);
}

export function semanticSearch(query) {
  return post("/search/semantic", query);
}

export function quickSearch(q, limit = 5) {
  return get("/search/quick", { q, limit });
}

export function globalSearch(q, options = {}) {
  return get("/search/global", {
    q,
    scope: options.scope || "all",
    database_id: options.databaseId || "",
    book_id: options.bookId || "",
    limit: options.limit || 20,
  });
}
