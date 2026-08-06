package com.library.assistant.controller;

import com.library.assistant.dto.BookDTO;
import com.library.assistant.service.BookService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/books")
@CrossOrigin(origins = "*") // CORS handles cross-origin requests
public class BookController {

    private final BookService bookService;

    @Autowired
    public BookController(BookService bookService) {
        this.bookService = bookService;
    }

    @GetMapping
    public ResponseEntity<List<BookDTO>> getAllBooks(
            @RequestParam(defaultValue = "title") String sortBy,
            @RequestParam(defaultValue = "asc") String direction) {
        List<BookDTO> books = bookService.getAllBooks(sortBy, direction);
        return ResponseEntity.ok(books);
    }

    @GetMapping("/{id}")
    public ResponseEntity<BookDTO> getBookById(@PathVariable Long id) {
        BookDTO book = bookService.getBookById(id);
        return ResponseEntity.ok(book);
    }

    @PostMapping
    public ResponseEntity<BookDTO> createBook(@Valid @RequestBody BookDTO bookDTO) {
        BookDTO createdBook = bookService.createBook(bookDTO);
        return new ResponseEntity<>(createdBook, HttpStatus.CREATED);
    }

    @PutMapping("/{id}")
    public ResponseEntity<BookDTO> updateBook(@PathVariable Long id, @Valid @RequestBody BookDTO bookDTO) {
        BookDTO updatedBook = bookService.updateBook(id, bookDTO);
        return ResponseEntity.ok(updatedBook);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteBook(@PathVariable Long id) {
        bookService.deleteBook(id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/search")
    public ResponseEntity<List<BookDTO>> searchBooks(@RequestParam String query) {
        List<BookDTO> books = bookService.searchBooks(query);
        return ResponseEntity.ok(books);
    }

    @GetMapping("/category/{category}")
    public ResponseEntity<List<BookDTO>> getBooksByCategory(@PathVariable String category) {
        List<BookDTO> books = bookService.getBooksByCategory(category);
        return ResponseEntity.ok(books);
    }

    @GetMapping("/categories")
    public ResponseEntity<List<String>> getCategories() {
        List<String> categories = bookService.getCategories();
        return ResponseEntity.ok(categories);
    }

    @GetMapping("/stats")
    public ResponseEntity<Map<String, Object>> getLibraryStats() {
        Map<String, Object> stats = bookService.getLibraryStats();
        return ResponseEntity.ok(stats);
    }
}
