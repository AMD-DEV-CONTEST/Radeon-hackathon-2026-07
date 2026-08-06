package com.linguabot.repository;

import com.linguabot.model.Certificate;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface CertificateRepository extends MongoRepository<Certificate, String> {
    List<Certificate> findByUserId(String userId);
    Optional<Certificate> findByUserIdAndCourseName(String userId, String courseName);
    Optional<Certificate> findByVerificationCode(String verificationCode);
}
