package com.linguabot.repository;

import com.linguabot.model.Badge;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface BadgeRepository extends MongoRepository<Badge, String> {
    List<Badge> findByUserId(String userId);
    List<Badge> findByUserIdOrderByEarnedAtDesc(String userId);
}
