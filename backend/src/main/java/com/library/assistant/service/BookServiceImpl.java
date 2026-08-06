package com.library.assistant.service;

import com.library.assistant.dto.BookDTO;
import com.library.assistant.entity.Book;
import com.library.assistant.exception.ResourceNotFoundException;
import com.library.assistant.repository.BookRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@Transactional
public class BookServiceImpl implements BookService {

    private final BookRepository bookRepository;

    @Autowired
    public BookServiceImpl(BookRepository bookRepository) {
        this.bookRepository = bookRepository;
    }

    @Override
    public List<BookDTO> getAllBooks(String sortBy, String direction) {
        Sort sort = Sort.by(Sort.Direction.fromString(direction), sortBy);
        return bookRepository.findAll(sort)
                .stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    @Override
    public BookDTO getBookById(Long id) {
        Book book = bookRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Book not found with id: " + id));
        return convertToDTO(book);
    }

    @Override
    public BookDTO createBook(BookDTO bookDTO) {
        Book book = convertToEntity(bookDTO);
        Book savedBook = bookRepository.save(book);
        return convertToDTO(savedBook);
    }

    @Override
    public BookDTO updateBook(Long id, BookDTO bookDTO) {
        Book existingBook = bookRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Book not found with id: " + id));

        existingBook.setTitle(bookDTO.getTitle());
        existingBook.setAuthor(bookDTO.getAuthor());
        existingBook.setCategory(bookDTO.getCategory());
        existingBook.setDescription(bookDTO.getDescription());
        existingBook.setPublisher(bookDTO.getPublisher());
        existingBook.setIsbn(bookDTO.getIsbn());
        existingBook.setShelfNumber(bookDTO.getShelfNumber());
        existingBook.setQuantity(bookDTO.getQuantity());
        existingBook.setAvailability(bookDTO.getQuantity() > 0);
        if (bookDTO.getImageUrl() != null && !bookDTO.getImageUrl().isBlank()) {
            existingBook.setImageUrl(bookDTO.getImageUrl());
        }

        Book updatedBook = bookRepository.save(existingBook);
        return convertToDTO(updatedBook);
    }

    @Override
    public void deleteBook(Long id) {
        Book book = bookRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Book not found with id: " + id));
        bookRepository.delete(book);
    }

    @Override
    public List<BookDTO> searchBooks(String query) {
        if (query == null || query.trim().isEmpty()) {
            return getAllBooks("title", "asc");
        }
        return bookRepository.searchBooks(query)
                .stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    @Override
    public List<BookDTO> getBooksByCategory(String category) {
        return bookRepository.findByCategoryIgnoreCase(category)
                .stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    @Override
    public List<String> getCategories() {
        return bookRepository.findDistinctCategories();
    }

    @Override
    public Map<String, Object> getLibraryStats() {
        Map<String, Object> stats = new HashMap<>();
        long totalBooks = bookRepository.count();
        long availableBooks = bookRepository.countByAvailabilityTrue();
        long borrowedBooks = bookRepository.countByAvailabilityFalse(); // Out of stock
        long totalCategories = bookRepository.findDistinctCategories().size();

        // Fetch recent books (limit to 5)
        Sort recentSort = Sort.by(Sort.Direction.DESC, "createdAt");
        List<BookDTO> recentBooks = bookRepository.findAll(recentSort)
                .stream()
                .limit(5)
                .map(this::convertToDTO)
                .collect(Collectors.toList());

        stats.put("totalBooks", totalBooks);
        stats.put("availableBooks", availableBooks);
        stats.put("borrowedBooks", borrowedBooks);
        stats.put("totalCategories", totalCategories);
        stats.put("recentBooks", recentBooks);

        return stats;
    }

    private BookDTO convertToDTO(Book book) {
        return BookDTO.builder()
                .id(book.getId())
                .title(book.getTitle())
                .author(book.getAuthor())
                .category(book.getCategory())
                .description(book.getDescription())
                .publisher(book.getPublisher())
                .isbn(book.getIsbn())
                .shelfNumber(book.getShelfNumber())
                .quantity(book.getQuantity())
                .availability(book.getAvailability())
                .imageUrl(book.getImageUrl())
                .createdAt(book.getCreatedAt())
                .updatedAt(book.getUpdatedAt())
                .build();
    }

    private Book convertToEntity(BookDTO dto) {
        return Book.builder()
                .id(dto.getId())
                .title(dto.getTitle())
                .author(dto.getAuthor())
                .category(dto.getCategory())
                .description(dto.getDescription())
                .publisher(dto.getPublisher())
                .isbn(dto.getIsbn())
                .shelfNumber(dto.getShelfNumber())
                .quantity(dto.getQuantity())
                .availability(dto.getQuantity() != null && dto.getQuantity() > 0)
                .imageUrl(dto.getImageUrl())
                .build();
    }
}
