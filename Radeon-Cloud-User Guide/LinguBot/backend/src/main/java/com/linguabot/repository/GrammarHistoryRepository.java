package com.linguabot.repository;

import com.linguabot.model.GrammarHistory;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GrammarHistoryRepository extends MongoRepository<GrammarHistory, String> {
    List<GrammarHistory> findByUserIdOrderByCreatedAtDesc(String userId);
    List<GrammarHistory> findTop3ByUserIdOrderByCreatedAtDesc(String userId);
}
