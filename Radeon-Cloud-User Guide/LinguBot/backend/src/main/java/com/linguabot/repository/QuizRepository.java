package com.linguabot.repository;

import com.linguabot.model.Quiz;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface QuizRepository extends MongoRepository<Quiz, String> {
    List<Quiz> findByCategory(String category);
    List<Quiz> findByDifficulty(String difficulty);
}
