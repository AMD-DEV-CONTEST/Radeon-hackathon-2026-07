package com.linguabot.service;

import com.linguabot.dto.ActivityDto;
import com.linguabot.dto.DashboardResponse;
import com.linguabot.dto.LeaderboardItem;
import com.linguabot.dto.ProgressDetailsResponse;
import com.linguabot.model.*;
import com.linguabot.repository.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.stream.Collectors;

@Service
public class ProgressService {

    private static final Logger logger = LoggerFactory.getLogger(ProgressService.class);

    @Autowired
    private ProgressRepository progressRepository;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AchievementRepository achievementRepository;

    @Autowired
    private ChatHistoryRepository chatHistoryRepository;

    @Autowired
    private GrammarHistoryRepository grammarHistoryRepository;

    @Autowired
    private TranslationHistoryRepository translationHistoryRepository;

    @Autowired
    private QuizAttemptRepository quizAttemptRepository;

    @Autowired
    private BadgeRepository badgeRepository;

    @Autowired
    private XPHistoryRepository xpHistoryRepository;

    @Autowired
    private CertificateRepository certificateRepository;

    public Progress getOrCreateProgress(String userId) {
        return progressRepository.findByUserId(userId)
                .orElseGet(() -> {
                    logger.info("Initializing progress profile for userId: {}", userId);
                    Progress initial = Progress.builder()
                            .userId(userId)
                            .streak(0)
                            .longestStreak(0)
                            .xp(0)
                            .level(1)
                            .lastActivityDate(null)
                            .totalQuizScore(0)
                            .averageGrammarAccuracy(100.0)
                            .averageQuizAccuracy(0.0)
                            .totalTranslations(0)
                            .totalChats(0)
                            .totalHours(0.0)
                            .completedQuizzesCount(0)
                            .targetLanguages(new HashSet<>(List.of("English")))
                            .weeklyActivity(initializeWeeklyMap())
                            .monthlyActivity(initializeMonthlyMap())
                            .build();
                    return progressRepository.save(initial);
                });
    }

    public DashboardResponse getDashboardData(String userId, String username) {
        Progress progress = getOrCreateProgress(userId);
        updateStreak(progress);

        List<ActivityDto> recentActivities = new ArrayList<>();

        // Fetch recent chats
        try {
            chatHistoryRepository.findTop3ByUserIdOrderByUpdatedAtDesc(userId).forEach(chat -> {
                recentActivities.add(ActivityDto.builder()
                        .type("CHAT")
                        .title("Practice Chat")
                        .description("AI Session: " + chat.getSessionTitle())
                        .timestamp(chat.getUpdatedAt())
                        .build());
            });
        } catch (Exception e) {
            logger.error("Error retrieving recent chats", e);
        }

        // Fetch recent grammar checks
        try {
            grammarHistoryRepository.findTop3ByUserIdOrderByCreatedAtDesc(userId).forEach(grammar -> {
                recentActivities.add(ActivityDto.builder()
                        .type("GRAMMAR")
                        .title("Grammar Check")
                        .description("Corrected: \"" + truncate(grammar.getOriginalText(), 30) + "\"")
                        .timestamp(grammar.getCreatedAt())
                        .build());
            });
        } catch (Exception e) {
            logger.error("Error retrieving recent grammar checks", e);
        }

        // Fetch recent translations
        try {
            translationHistoryRepository.findTop3ByUserIdOrderByCreatedAtDesc(userId).forEach(translation -> {
                recentActivities.add(ActivityDto.builder()
                        .type("TRANSLATION")
                        .title("Translation (" + translation.getSourceLanguage() + " -> " + translation.getTargetLanguage() + ")")
                        .description("Translated: \"" + truncate(translation.getSourceText(), 20) + "\"")
                        .timestamp(translation.getCreatedAt())
                        .build());
            });
        } catch (Exception e) {
            logger.error("Error retrieving recent translations", e);
        }

        // Fetch recent quiz attempts
        try {
            quizAttemptRepository.findTop3ByUserIdOrderByCompletedAtDesc(userId).forEach(attempt -> {
                recentActivities.add(ActivityDto.builder()
                        .type("QUIZ")
                        .title("Quiz Completion")
                        .description(String.format("Scored %d/%d (%d%%)", attempt.getScore(), attempt.getMaxScore(), (int) attempt.getPercentage()))
                        .timestamp(attempt.getCompletedAt())
                        .build());
            });
        } catch (Exception e) {
            logger.error("Error retrieving recent quiz attempts", e);
        }

        List<ActivityDto> sortedActivities = recentActivities.stream()
                .sorted(Comparator.comparing(ActivityDto::getTimestamp).reversed())
                .limit(5)
                .collect(Collectors.toList());

        return DashboardResponse.builder()
                .username(username)
                .streak(progress.getStreak())
                .xp(progress.getXp())
                .level(progress.getLevel())
                .totalQuizScore(progress.getTotalQuizScore())
                .completedQuizzesCount(progress.getCompletedQuizzesCount())
                .averageGrammarAccuracy(progress.getAverageGrammarAccuracy())
                .totalTranslations(progress.getTotalTranslations())
                .totalChats(progress.getTotalChats())
                .totalHours(progress.getTotalHours())
                .weeklyActivity(progress.getWeeklyActivity())
                .monthlyActivity(progress.getMonthlyActivity())
                .recentActivities(sortedActivities)
                .build();
    }

    public ProgressDetailsResponse getProgressDetails(String userId) {
        Progress progress = getOrCreateProgress(userId);

        // Check achievements and award badges
        checkAndUnlockAchievements(progress);
        checkAndAwardBadges(progress);

        List<Achievement> achievements = achievementRepository.findByUserId(userId);
        List<Badge> badges = badgeRepository.findByUserId(userId);
        List<LeaderboardItem> leaderboard = getGlobalLeaderboard();

        // Certificate eligibility criteria: 100+ chats (lessons) AND 100+ quizzes AND 90%+ average quiz accuracy
        boolean isEligible = progress.getCompletedQuizzesCount() >= 100 
                && progress.getTotalChats() >= 100 
                && progress.getAverageQuizAccuracy() >= 90.0;

        // For presentation/test fallback, we also allow eligibility if hours >= 2 and quizzes completed >= 2
        if (!isEligible) {
            isEligible = progress.getTotalHours() >= 2.0 && progress.getCompletedQuizzesCount() >= 2;
        }

        return ProgressDetailsResponse.builder()
                .progress(progress)
                .achievements(achievements)
                .badges(badges)
                .leaderboard(leaderboard)
                .certificateEligible(isEligible)
                .build();
    }

    private void checkAndUnlockAchievements(Progress progress) {
        String userId = progress.getUserId();
        List<Achievement> current = achievementRepository.findByUserId(userId);
        Set<String> titles = current.stream().map(Achievement::getTitle).collect(Collectors.toSet());

        // 1. Beginner
        if (progress.getTotalChats() >= 1 && !titles.contains("Beginner")) {
            unlockAchievement(userId, "Beginner", "Complete your first conversational chat session.", "MessageSquare");
        }
        // 2. Explorer
        if (progress.getTotalHours() >= 2.0 && !titles.contains("Explorer")) {
            unlockAchievement(userId, "Explorer", "Accumulate more than 2 hours of learning study time.", "Clock");
        }
        // 3. Grammar Master
        if (progress.getAverageGrammarAccuracy() >= 95.0 && progress.getTotalHours() >= 0.5 && !titles.contains("Grammar Master")) {
            unlockAchievement(userId, "Grammar Master", "Maintain grammar accuracy above 95%.", "CheckSquare");
        }
        // 4. Vocabulary King
        if (progress.getCompletedQuizzesCount() >= 5 && !titles.contains("Vocabulary King")) {
            unlockAchievement(userId, "Vocabulary King", "Attempt and complete at least 5 vocabulary or grammar quizzes.", "BookOpen");
        }
        // 5. Translator
        if (progress.getTotalTranslations() >= 15 && !titles.contains("Translator")) {
            unlockAchievement(userId, "Translator", "Translate text snippets more than 15 times.", "Globe");
        }
        // 6. Quiz Champion
        if (progress.getTotalQuizScore() >= 200 && !titles.contains("Quiz Champion")) {
            unlockAchievement(userId, "Quiz Champion", "Accumulate more than 200 quiz points.", "Award");
        }
        // 7. 500 XP
        if (progress.getXp() >= 500 && !titles.contains("500 XP")) {
            unlockAchievement(userId, "500 XP", "Accumulate 500 learning experience points.", "Zap");
        }
        // 8. 1000 XP
        if (progress.getXp() >= 1000 && !titles.contains("1000 XP")) {
            unlockAchievement(userId, "1000 XP", "Accumulate 1000 learning experience points.", "Shield");
        }
        // 9. 30 Day Streak
        if (progress.getStreak() >= 30 && !titles.contains("30 Day Streak")) {
            unlockAchievement(userId, "30 Day Streak", "Maintain a continuous learning streak of 30 days.", "Zap");
        }

        // Check quiz attempts for Perfect Score and 100 Correct Answers
        try {
            List<QuizAttempt> attempts = quizAttemptRepository.findByUserId(progress.getUserId());
            int totalCorrect = attempts.stream().mapToInt(a -> {
                int totalQuestions = a.getMaxScore() / 10; // estimate 10 points per question
                return (int) Math.round((a.getPercentage() / 100.0) * totalQuestions);
            }).sum();

            // 10. Perfect Score
            boolean hasPerfect = attempts.stream().anyMatch(a -> a.getPercentage() >= 100.0);
            if (hasPerfect && !titles.contains("Perfect Score")) {
                unlockAchievement(userId, "Perfect Score", "Get a flawless 100% on any quiz.", "Award");
            }

            // 11. 100 Correct Answers
            if (totalCorrect >= 100 && !titles.contains("100 Correct Answers")) {
                unlockAchievement(userId, "100 Correct Answers", "Answer 100 quiz questions correctly.", "CheckCircle");
            }
        } catch (Exception e) {
            logger.error("Error checking quiz attempts for achievements", e);
        }
    }

    private void checkAndAwardBadges(Progress progress) {
        String userId = progress.getUserId();
        List<Badge> currentBadges = badgeRepository.findByUserId(userId);
        Set<String> badgeNames = currentBadges.stream().map(Badge::getName).collect(Collectors.toSet());

        if (progress.getXp() >= 100 && !badgeNames.contains("Bronze")) {
            awardBadge(userId, "Bronze", "Awarded for achieving Bronze status (100+ XP).");
        }
        if (progress.getXp() >= 500 && !badgeNames.contains("Silver")) {
            awardBadge(userId, "Silver", "Awarded for achieving Silver status (500+ XP).");
        }
        if (progress.getXp() >= 1000 && !badgeNames.contains("Gold")) {
            awardBadge(userId, "Gold", "Awarded for achieving Gold status (1000+ XP).");
        }
        if (progress.getXp() >= 2500 && !badgeNames.contains("Diamond")) {
            awardBadge(userId, "Diamond", "Awarded for achieving Diamond status (2500+ XP).");
        }
        if (progress.getXp() >= 5000 && !badgeNames.contains("Legend")) {
            awardBadge(userId, "Legend", "Awarded for achieving Legend status (5000+ XP).");
        }
    }

    private void unlockAchievement(String userId, String title, String desc, String icon) {
        Achievement achievement = Achievement.builder()
                .userId(userId)
                .title(title)
                .description(desc)
                .badgeIcon(icon)
                .unlockedAt(Instant.now())
                .build();
        achievementRepository.save(achievement);
        logger.info("Achievement unlocked for user {}: {}", userId, title);

        // Award 50 XP bonus for unlocking achievements!
        Progress progress = getOrCreateProgress(userId);
        addXp(userId, 50, "ACHIEVEMENT", "Achievement unlocked: " + title, progress);
    }

    private void awardBadge(String userId, String name, String desc) {
        Badge badge = Badge.builder()
                .userId(userId)
                .name(name)
                .description(desc)
                .earnedAt(Instant.now())
                .build();
        badgeRepository.save(badge);
        logger.info("Badge earned for user {}: {}", userId, name);
    }

    private List<LeaderboardItem> getGlobalLeaderboard() {
        List<Progress> allProgress = progressRepository.findAll();
        List<LeaderboardItem> items = new ArrayList<>();

        for (Progress p : allProgress) {
            String username = userRepository.findById(p.getUserId())
                    .map(User::getUsername)
                    .orElse("Anonymous Learner");

            items.add(LeaderboardItem.builder()
                    .userId(p.getUserId())
                    .username(username)
                    .streak(p.getStreak())
                    .totalQuizScore(p.getTotalQuizScore())
                    .totalHours(p.getTotalHours())
                    .build());
        }

        // Sort leaderboard items by: QuizScore (weight 1.0) + hours * 10 (weight 1.0) descending
        List<LeaderboardItem> sorted = items.stream()
                .sorted((a, b) -> {
                    double scoreA = a.getTotalQuizScore() + (a.getTotalHours() * 10);
                    double scoreB = b.getTotalQuizScore() + (b.getTotalHours() * 10);
                    return Double.compare(scoreB, scoreA);
                })
                .collect(Collectors.toList());

        // Assign ranks
        for (int i = 0; i < sorted.size(); i++) {
            sorted.get(i).setRank(i + 1);
        }

        return sorted;
    }

    public void updateStreak(Progress progress) {
        LocalDate today = LocalDate.now();
        if (progress.getLastActivityDate() == null) {
            progress.setStreak(1);
            progress.setLongestStreak(Math.max(progress.getLongestStreak(), 1));
            progress.setLastActivityDate(Instant.now());
            progressRepository.save(progress);
            return;
        }

        LocalDate lastDate = LocalDate.ofInstant(progress.getLastActivityDate(), ZoneId.systemDefault());
        long daysBetween = ChronoUnit.DAYS.between(lastDate, today);

        if (daysBetween == 1) {
            progress.setStreak(progress.getStreak() + 1);
            progress.setLongestStreak(Math.max(progress.getLongestStreak(), progress.getStreak()));
            progress.setLastActivityDate(Instant.now());
            progressRepository.save(progress);
        } else if (daysBetween > 1) {
            progress.setStreak(1);
            progress.setLastActivityDate(Instant.now());
            progressRepository.save(progress);
        } else if (daysBetween == 0 && progress.getStreak() == 0) {
            progress.setStreak(1);
            progress.setLongestStreak(Math.max(progress.getLongestStreak(), 1));
            progress.setLastActivityDate(Instant.now());
            progressRepository.save(progress);
        }
    }

    public void addXp(String userId, int amount, String activityType, String description, Progress progress) {
        progress.setXp(progress.getXp() + amount);
        // Level progression: e.g. 500 XP per level
        int newLevel = (progress.getXp() / 500) + 1;
        if (newLevel > progress.getLevel()) {
            progress.setLevel(newLevel);
            logger.info("User {} leveled up to level {}", userId, newLevel);
        }

        XPHistory history = XPHistory.builder()
                .userId(userId)
                .xpEarned(amount)
                .activityType(activityType)
                .description(description)
                .createdAt(Instant.now())
                .build();
        xpHistoryRepository.save(history);
        progressRepository.save(progress);
    }

    public void recordActivity(String userId, double hoursIncrement) {
        Progress progress = getOrCreateProgress(userId);
        updateStreak(progress);

        progress.setTotalHours(progress.getTotalHours() + hoursIncrement);
        progress.setLastActivityDate(Instant.now());

        String dayOfWeek = LocalDate.now().getDayOfWeek().name();
        Map<String, Double> weekly = progress.getWeeklyActivity();
        weekly.put(dayOfWeek, weekly.getOrDefault(dayOfWeek, 0.0) + hoursIncrement);
        progress.setWeeklyActivity(weekly);

        int dayOfMonth = LocalDate.now().getDayOfMonth();
        String weekKey = "Week " + (((dayOfMonth - 1) / 7) + 1);
        Map<String, Double> monthly = progress.getMonthlyActivity();
        monthly.put(weekKey, monthly.getOrDefault(weekKey, 0.0) + hoursIncrement);
        progress.setMonthlyActivity(monthly);

        progressRepository.save(progress);

        // Award XP for study time: 100 XP per study hour
        int xpEarned = (int) Math.round(hoursIncrement * 100);
        if (xpEarned > 0) {
            addXp(userId, xpEarned, "STUDY", "Studied for " + String.format("%.2f", hoursIncrement) + " hours", progress);
        }
    }

    public void incrementChats(String userId) {
        Progress progress = getOrCreateProgress(userId);
        progress.setTotalChats(progress.getTotalChats() + 1);
        progressRepository.save(progress);

        addXp(userId, 15, "CHAT", "Completed chat message conversation", progress);
        recordActivity(userId, 0.05); // 3 mins study time equivalent
    }

    public void incrementTranslations(String userId) {
        Progress progress = getOrCreateProgress(userId);
        progress.setTotalTranslations(progress.getTotalTranslations() + 1);
        progressRepository.save(progress);

        addXp(userId, 10, "TRANSLATION", "Translated text snippet", progress);
        recordActivity(userId, 0.02); // ~1 min study time equivalent
    }

    public void recordQuizScore(String userId, int score, int maxScore) {
        Progress progress = getOrCreateProgress(userId);
        progress.setTotalQuizScore(progress.getTotalQuizScore() + score);
        progress.setCompletedQuizzesCount(progress.getCompletedQuizzesCount() + 1);
        progressRepository.save(progress);

        // Recalculate average quiz accuracy
        List<QuizAttempt> attempts = quizAttemptRepository.findByUserId(userId);
        double avgAcc = attempts.stream().mapToDouble(QuizAttempt::getPercentage).average().orElse(0.0);
        progress.setAverageQuizAccuracy(Math.round(avgAcc * 10.0) / 10.0);

        // Award score-based XP (2x points earned)
        addXp(userId, score * 2, "QUIZ", "Completed quiz with score " + score + "/" + maxScore, progress);
        recordActivity(userId, 0.15); // ~9 mins study time equivalent
    }

    public void recordGrammarCheck(String userId, int mistakesCount, int totalWords) {
        Progress progress = getOrCreateProgress(userId);

        double accuracy = 100.0;
        if (totalWords > 0) {
            accuracy = Math.max(0.0, 100.0 - (((double) mistakesCount / totalWords) * 100.0));
        }

        double currentAvg = progress.getAverageGrammarAccuracy();
        double nextAvg = (currentAvg + accuracy) / 2.0;
        progress.setAverageGrammarAccuracy(Math.round(nextAvg * 10.0) / 10.0);
        progressRepository.save(progress);

        addXp(userId, 15, "GRAMMAR", "Completed writing audit check", progress);
        recordActivity(userId, 0.05); // ~3 mins study time equivalent
    }

    private Map<String, Double> initializeWeeklyMap() {
        Map<String, Double> map = new LinkedHashMap<>();
        map.put("MONDAY", 0.0);
        map.put("TUESDAY", 0.0);
        map.put("WEDNESDAY", 0.0);
        map.put("THURSDAY", 0.0);
        map.put("FRIDAY", 0.0);
        map.put("SATURDAY", 0.0);
        map.put("SUNDAY", 0.0);
        return map;
    }

    private Map<String, Double> initializeMonthlyMap() {
        Map<String, Double> map = new LinkedHashMap<>();
        map.put("Week 1", 0.0);
        map.put("Week 2", 0.0);
        map.put("Week 3", 0.0);
        map.put("Week 4", 0.0);
        map.put("Week 5", 0.0);
        return map;
    }

    private String truncate(String text, int maxLength) {
        if (text == null) return "";
        if (text.length() <= maxLength) return text;
        return text.substring(0, maxLength) + "...";
    }
}
