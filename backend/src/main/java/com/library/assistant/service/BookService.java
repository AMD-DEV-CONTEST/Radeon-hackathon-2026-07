package com.library.assistant.service;

import com.library.assistant.dto.BookDTO;
import java.util.List;
import java.util.Map;

public interface BookService {
    List<BookDTO> getAllBooks(String sortBy, String direction);
    BookDTO getBookById(Long id);
    BookDTO createBook(BookDTO bookDTO);
    BookDTO updateBook(Long id, BookDTO bookDTO);
    void deleteBook(Long id);
    List<BookDTO> searchBooks(String query);
    List<BookDTO> getBooksByCategory(String category);
    List<String> getCategories();
    Map<String, Object> getLibraryStats();
}
