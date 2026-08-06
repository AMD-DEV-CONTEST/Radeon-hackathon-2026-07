package com.linguabot.repository;

import com.linguabot.model.XPHistory;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface XPHistoryRepository extends MongoRepository<XPHistory, String> {
    List<XPHistory> findByUserIdOrderByCreatedAtDesc(String userId);
    List<XPHistory> findTop10ByUserIdOrderByCreatedAtDesc(String userId);
}
