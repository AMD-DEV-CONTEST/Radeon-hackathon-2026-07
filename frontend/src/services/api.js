import axios from 'axios';

const API_BASE_URL = 'http://localhost:8080/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const bookService = {
  getBooks: async (sortBy = 'title', direction = 'asc') => {
    const response = await api.get(`/books?sortBy=${sortBy}&direction=${direction}`);
    return response.data;
  },

  getBookById: async (id) => {
    const response = await api.get(`/books/${id}`);
    return response.data;
  },

  createBook: async (bookData) => {
    const response = await api.post('/books', bookData);
    return response.data;
  },

  updateBook: async (id, bookData) => {
    const response = await api.put(`/books/${id}`, bookData);
    return response.data;
  },

  deleteBook: async (id) => {
    const response = await api.delete(`/books/${id}`);
    return response.data;
  },

  searchBooks: async (query) => {
    const response = await api.get(`/books/search?query=${encodeURIComponent(query)}`);
    return response.data;
  },

  getBooksByCategory: async (category) => {
    const response = await api.get(`/books/category/${encodeURIComponent(category)}`);
    return response.data;
  },

  getCategories: async () => {
    const response = await api.get('/books/categories');
    return response.data;
  },

  getLibraryStats: async () => {
    const response = await api.get('/books/stats');
    return response.data;
  },
};

export const aiService = {
  chat: async (question) => {
    const response = await api.post('/ai/chat', { question });
    return response.data;
  },
};

export default api;
