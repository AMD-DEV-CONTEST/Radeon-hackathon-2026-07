package com.linguabot.repository;

import com.linguabot.model.TranslationHistory;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface TranslationHistoryRepository extends MongoRepository<TranslationHistory, String> {
    List<TranslationHistory> findByUserIdOrderByCreatedAtDesc(String userId);
    List<TranslationHistory> findTop3ByUserIdOrderByCreatedAtDesc(String userId);
    List<TranslationHistory> findByUserIdAndIsFavoriteOrderByCreatedAtDesc(String userId, boolean isFavorite);
}
