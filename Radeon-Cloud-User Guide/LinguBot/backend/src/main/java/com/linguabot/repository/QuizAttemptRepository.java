package com.linguabot.repository;

import com.linguabot.model.QuizAttempt;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface QuizAttemptRepository extends MongoRepository<QuizAttempt, String> {
    List<QuizAttempt> findByUserId(String userId);
    List<QuizAttempt> findByUserIdOrderByCompletedAtDesc(String userId);
    List<QuizAttempt> findTop3ByUserIdOrderByCompletedAtDesc(String userId);
}
