package com.linguabot.repository;

import com.linguabot.model.Progress;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface ProgressRepository extends MongoRepository<Progress, String> {
    Optional<Progress> findByUserId(String userId);
}
