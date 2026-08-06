package com.indusmind.repository;

import com.indusmind.domain.DocumentRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface DocumentRepository extends JpaRepository<DocumentRecord, Long> {
    List<DocumentRecord> findAllByOrderByUploadedAtDesc();
    long countByStatus(String status);
}

