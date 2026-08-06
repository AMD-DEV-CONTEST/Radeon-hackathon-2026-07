package com.indusmind.repository;

import com.indusmind.domain.QueryLog;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface QueryLogRepository extends JpaRepository<QueryLog, Long> {
    List<QueryLog> findTop5ByOrderByCreatedAtDesc();
}

