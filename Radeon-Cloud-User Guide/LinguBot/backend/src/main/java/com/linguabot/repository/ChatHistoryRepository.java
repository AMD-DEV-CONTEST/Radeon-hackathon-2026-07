package com.linguabot.repository;

import com.linguabot.model.ChatHistory;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatHistoryRepository extends MongoRepository<ChatHistory, String> {
    List<ChatHistory> findByUserIdOrderByUpdatedAtDesc(String userId);
    List<ChatHistory> findTop3ByUserIdOrderByUpdatedAtDesc(String userId);
    List<ChatHistory> findByUserIdAndSessionTitleContainingIgnoreCaseOrderByUpdatedAtDesc(String userId, String query);
}
