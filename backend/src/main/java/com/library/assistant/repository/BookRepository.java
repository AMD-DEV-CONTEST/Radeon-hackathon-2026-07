package com.library.assistant.repository;

import com.library.assistant.entity.Book;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface BookRepository extends JpaRepository<Book, Long> {

    List<Book> findByCategoryIgnoreCase(String category);

    @Query("SELECT b FROM Book b WHERE " +
            "LOWER(b.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.author) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.category) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.description) LIKE LOWER(CONCAT('%', :keyword, '%'))")
    List<Book> searchBooks(@Param("keyword") String keyword);

    @Query("SELECT b FROM Book b WHERE b.availability = true AND (" +
            "LOWER(b.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.author) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.category) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(b.description) LIKE LOWER(CONCAT('%', :keyword, '%')))")
    List<Book> searchAvailableBooks(@Param("keyword") String keyword);

    List<Book> findByAvailabilityTrue();

    @Query("SELECT DISTINCT b.category FROM Book b")
    List<String> findDistinctCategories();

    long countByAvailabilityTrue();
    long countByAvailabilityFalse();
}
