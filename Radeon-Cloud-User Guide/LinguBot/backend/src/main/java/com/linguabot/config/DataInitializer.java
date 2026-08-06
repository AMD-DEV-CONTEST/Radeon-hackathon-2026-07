package com.linguabot.config;

import com.linguabot.model.*;
import com.linguabot.repository.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.*;

@Component
public class DataInitializer implements CommandLineRunner {

    private static final Logger logger = LoggerFactory.getLogger(DataInitializer.class);

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private ProgressRepository progressRepository;

    @Autowired
    private QuizRepository quizRepository;

    @Autowired
    private FeedbackRepository feedbackRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Override
    public void run(String... args) throws Exception {
        initializeUsers();
        initializeQuizzes();
        initializeFeedback();
    }

    private void initializeUsers() {
        if (userRepository.count() > 0) {
            return;
        }

        logger.info("Initializing sample users and leaderboard profiles...");

        // 1. Admin User
        User admin = User.builder()
                .username("admin")
                .email("admin@linguabot.com")
                .password(passwordEncoder.encode("password123"))
                .roles(Set.of(Role.ROLE_USER, Role.ROLE_ADMIN))
                .createdAt(Instant.now())
                .updatedAt(Instant.now())
                .build();
        userRepository.save(admin);

        Progress adminProgress = Progress.builder()
                .userId(admin.getId())
                .streak(2)
                .lastActivityDate(Instant.now())
                .totalQuizScore(60)
                .averageGrammarAccuracy(95.0)
                .totalTranslations(8)
                .totalChats(5)
                .totalHours(2.5)
                .completedQuizzesCount(2)
                .weeklyActivity(createMockWeeklyMap(0.5, 0.8, 1.2))
                .monthlyActivity(createMockMonthlyMap(2.5))
                .build();
        progressRepository.save(adminProgress);

        // 2. Standard User
        User student = User.builder()
                .username("student")
                .email("student@linguabot.com")
                .password(passwordEncoder.encode("password123"))
                .roles(Set.of(Role.ROLE_USER))
                .createdAt(Instant.now())
                .updatedAt(Instant.now())
                .build();
        userRepository.save(student);

        Progress studentProgress = Progress.builder()
                .userId(student.getId())
                .streak(1)
                .lastActivityDate(Instant.now())
                .totalQuizScore(30)
                .averageGrammarAccuracy(88.0)
                .totalTranslations(4)
                .totalChats(2)
                .totalHours(1.0)
                .completedQuizzesCount(1)
                .weeklyActivity(createMockWeeklyMap(0.2, 0.4, 0.4))
                .monthlyActivity(createMockMonthlyMap(1.0))
                .build();
        progressRepository.save(studentProgress);

        // 3. Leaderboard Mock Users (so that the leaderboard looks fully populated and competitive)
        createLeaderboardMockUser("Elena_Polyglot", "elena@test.com", 8, 180, 94.0, 15, 20, 8.5);
        createLeaderboardMockUser("Hiroshi_JP", "hiroshi@test.com", 6, 120, 91.0, 10, 14, 5.0);
        createLeaderboardMockUser("Carlos_L", "carlos@test.com", 4, 90, 85.0, 12, 8, 4.2);
        createLeaderboardMockUser("Sophia_Learn", "sophia@test.com", 3, 50, 82.5, 5, 6, 2.0);

        logger.info("Sample users initialization complete.");
    }

    private void createLeaderboardMockUser(String username, String email, int streak, int score, double accuracy, int translations, int chats, double hours) {
        User u = User.builder()
                .username(username)
                .email(email)
                .password(passwordEncoder.encode("password123"))
                .roles(Set.of(Role.ROLE_USER))
                .createdAt(Instant.now().minusSeconds(86400 * 10))
                .updatedAt(Instant.now())
                .build();
        userRepository.save(u);

        Progress p = Progress.builder()
                .userId(u.getId())
                .streak(streak)
                .lastActivityDate(Instant.now().minusSeconds(3600 * 2))
                .totalQuizScore(score)
                .averageGrammarAccuracy(accuracy)
                .totalTranslations(translations)
                .totalChats(chats)
                .totalHours(hours)
                .completedQuizzesCount(score / 30 + 1)
                .weeklyActivity(createMockWeeklyMap(hours * 0.2, hours * 0.3, hours * 0.5))
                .monthlyActivity(createMockMonthlyMap(hours))
                .build();
        progressRepository.save(p);
    }

    private void initializeQuizzes() {
        if (quizRepository.count() > 0) {
            return;
        }

        logger.info("Initializing sample system quizzes...");

        // Quiz 1: Grammar Tenses Practice
        List<Quiz.Question> grammarQuestions = new ArrayList<>();
        grammarQuestions.add(Quiz.Question.builder()
                .id("q1")
                .questionText("She ____ to the gym every morning.")
                .type("MCQ")
                .options(List.of("go", "goes", "going"))
                .correctAnswer("goes")
                .points(10)
                .build());
        grammarQuestions.add(Quiz.Question.builder()
                .id("q2")
                .questionText("The past tense of 'run' is 'runned'.")
                .type("TRUE_FALSE")
                .options(List.of("True", "False"))
                .correctAnswer("False")
                .points(10)
                .build());
        grammarQuestions.add(Quiz.Question.builder()
                .id("q3")
                .questionText("Complete: I have ____ (be) to Paris twice.")
                .type("FILL_IN_BLANKS")
                .options(Collections.emptyList())
                .correctAnswer("been")
                .points(10)
                .build());

        Quiz quiz1 = Quiz.builder()
                .title("English Tenses Practice")
                .description("Test your knowledge of basic English tenses including simple present, simple past, and present perfect.")
                .category("Grammar")
                .difficulty("Medium")
                .timeLimit(6)
                .questions(grammarQuestions)
                .createdBy("System")
                .createdAt(Instant.now())
                .build();
        quizRepository.save(quiz1);

        // Quiz 2: Basic Vocabulary
        List<Quiz.Question> vocabQuestions = new ArrayList<>();
        vocabQuestions.add(Quiz.Question.builder()
                .id("q1")
                .questionText("What is the synonym of 'Happy'?")
                .type("MCQ")
                .options(List.of("Sad", "Joyful", "Angry"))
                .correctAnswer("Joyful")
                .points(10)
                .build());
        vocabQuestions.add(Quiz.Question.builder()
                .id("q2")
                .questionText("Write the opposite of 'hot' (4 letters).")
                .type("FILL_IN_BLANKS")
                .options(Collections.emptyList())
                .correctAnswer("cold")
                .points(10)
                .build());
        vocabQuestions.add(Quiz.Question.builder()
                .id("q3")
                .questionText("What is the French word for 'Apple'?")
                .type("MCQ")
                .options(List.of("Pomme", "Poire", "Banane"))
                .correctAnswer("Pomme")
                .points(10)
                .build());

        Quiz quiz2 = Quiz.builder()
                .title("Essential Vocabulary")
                .description("Challenge yourself with common english words, synonyms, antonyms, and language translations.")
                .category("Vocabulary")
                .difficulty("Easy")
                .timeLimit(6)
                .questions(vocabQuestions)
                .createdBy("System")
                .createdAt(Instant.now())
                .build();
        quizRepository.save(quiz2);

        logger.info("Sample quizzes initialization complete.");
    }

    private void initializeFeedback() {
        if (feedbackRepository.count() > 0) {
            return;
        }

        logger.info("Initializing sample feedback reviews...");

        Feedback fb1 = Feedback.builder()
                .username("Elena_Polyglot")
                .feedbackText("The AI chatbot is extremely responsive! I practiced conversational German for an hour and received perfect sentence-structure corrections.")
                .rating(5)
                .createdAt(Instant.now().minusSeconds(86400 * 2))
                .build();
        feedbackRepository.save(fb1);

        Feedback fb2 = Feedback.builder()
                .username("Hiroshi_JP")
                .feedbackText("Love the clean design system. Swapping between light and dark themes feels super smooth, and the weekly study hours chart helps me stay motivated.")
                .rating(4)
                .createdAt(Instant.now().minusSeconds(86400))
                .build();
        feedbackRepository.save(fb2);

        logger.info("Sample feedback initialization complete.");
    }

    private Map<String, Double> createMockWeeklyMap(double mon, double tue, double wed) {
        Map<String, Double> map = new LinkedHashMap<>();
        map.put("MONDAY", mon);
        map.put("TUESDAY", tue);
        map.put("WEDNESDAY", wed);
        map.put("THURSDAY", 0.0);
        map.put("FRIDAY", 0.0);
        map.put("SATURDAY", 0.0);
        map.put("SUNDAY", 0.0);
        return map;
    }

    private Map<String, Double> createMockMonthlyMap(double total) {
        Map<String, Double> map = new LinkedHashMap<>();
        map.put("Week 1", total * 0.4);
        map.put("Week 2", total * 0.6);
        map.put("Week 3", 0.0);
        map.put("Week 4", 0.0);
        map.put("Week 5", 0.0);
        return map;
    }
}
