package com.linguabot.service;

import com.linguabot.dto.AdminStatsResponse;
import com.linguabot.dto.AdminUserResponse;
import com.linguabot.dto.FeedbackRequest;
import com.linguabot.exception.ResourceNotFoundException;
import com.linguabot.model.*;
import com.linguabot.repository.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class AdminService {

    private static final Logger logger = LoggerFactory.getLogger(AdminService.class);

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private ProgressRepository progressRepository;

    @Autowired
    private ChatHistoryRepository chatHistoryRepository;

    @Autowired
    private GrammarHistoryRepository grammarHistoryRepository;

    @Autowired
    private TranslationHistoryRepository translationHistoryRepository;

    @Autowired
    private QuizRepository quizRepository;

    @Autowired
    private QuizAttemptRepository quizAttemptRepository;

    @Autowired
    private AchievementRepository achievementRepository;

    @Autowired
    private FeedbackRepository feedbackRepository;

    public List<AdminUserResponse> getUsersList() {
        return userRepository.findAll().stream()
                .map(user -> {
                    Progress p = progressRepository.findByUserId(user.getId()).orElse(null);
                    return AdminUserResponse.builder()
                            .id(user.getId())
                            .username(user.getUsername())
                            .email(user.getEmail())
                            .roles(user.getRoles().stream().map(Role::name).collect(Collectors.toList()))
                            .streak(p != null ? p.getStreak() : 0)
                            .totalHours(p != null ? p.getTotalHours() : 0.0)
                            .completedQuizzesCount(p != null ? p.getCompletedQuizzesCount() : 0)
                            .createdAt(user.getCreatedAt())
                            .build();
                })
                .collect(Collectors.toList());
    }

    public void deleteUser(String userId) {
        logger.warn("Initiating administrative deletion cascade for user: {}", userId);
        
        // Cascade delete all database collection instances mapped to this userId
        userRepository.deleteById(userId);
        progressRepository.findByUserId(userId).ifPresent(progressRepository::delete);
        
        chatHistoryRepository.findByUserIdOrderByUpdatedAtDesc(userId).forEach(chatHistoryRepository::delete);
        grammarHistoryRepository.findByUserIdOrderByCreatedAtDesc(userId).forEach(grammarHistoryRepository::delete);
        translationHistoryRepository.findByUserIdOrderByCreatedAtDesc(userId).forEach(translationHistoryRepository::delete);
        quizAttemptRepository.findByUserIdOrderByCompletedAtDesc(userId).forEach(quizAttemptRepository::delete);
        achievementRepository.findByUserId(userId).forEach(achievementRepository::delete);
        
        // Find and delete feedback submitted by this user
        feedbackRepository.findAll().stream()
                .filter(fb -> userId.equals(fb.getUserId()))
                .forEach(feedbackRepository::delete);

        logger.info("User {} and all associated resources deleted successfully.", userId);
    }

    public List<Quiz> getQuizzes() {
        return quizRepository.findAll();
    }

    public void deleteQuiz(String quizId) {
        if (!quizRepository.existsById(quizId)) {
            throw new ResourceNotFoundException("Quiz not found");
        }
        quizRepository.deleteById(quizId);
        logger.info("Quiz {} deleted by administrator", quizId);
    }

    public List<Feedback> getFeedback() {
        return feedbackRepository.findAllByOrderByCreatedAtDesc();
    }

    public void deleteFeedback(String feedbackId) {
        if (!feedbackRepository.existsById(feedbackId)) {
            throw new ResourceNotFoundException("Feedback not found");
        }
        feedbackRepository.deleteById(feedbackId);
        logger.info("Feedback {} deleted by administrator", feedbackId);
    }

    public Feedback submitFeedback(String userId, String username, FeedbackRequest request) {
        Feedback feedback = Feedback.builder()
                .userId(userId)
                .username(username)
                .feedbackText(request.getFeedbackText())
                .rating(request.getRating())
                .createdAt(Instant.now())
                .build();
        return feedbackRepository.save(feedback);
    }

    public AdminStatsResponse getPlatformStats() {
        long usersCount = userRepository.count();
        long quizCount = quizRepository.count();
        long feedbackCount = feedbackRepository.count();

        List<Progress> progressList = progressRepository.findAll();
        double hoursSum = progressList.stream().mapToDouble(Progress::getTotalHours).sum();
        double averageStreak = progressList.isEmpty() ? 0.0 : 
                progressList.stream().mapToInt(Progress::getStreak).average().orElse(0.0);

        return AdminStatsResponse.builder()
                .totalUsers(usersCount)
                .totalHoursSum(Math.round(hoursSum * 10.0) / 10.0)
                .totalQuizzesGenerated(quizCount)
                .totalFeedbackSubmitted(feedbackCount)
                .averageStreak(Math.round(averageStreak * 10.0) / 10.0)
                .build();
    }
}
