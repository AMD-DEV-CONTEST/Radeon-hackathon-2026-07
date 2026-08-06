package com.linguabot.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.linguabot.dto.QuizGenerateRequest;
import com.linguabot.dto.QuizSubmitRequest;
import com.linguabot.dto.QuizSubmitResponse;
import com.linguabot.exception.BadRequestException;
import com.linguabot.exception.ResourceNotFoundException;
import com.linguabot.model.Achievement;
import com.linguabot.model.Badge;
import com.linguabot.model.Quiz;
import com.linguabot.model.QuizAttempt;
import com.linguabot.repository.AchievementRepository;
import com.linguabot.repository.BadgeRepository;
import com.linguabot.repository.QuizAttemptRepository;
import com.linguabot.repository.QuizRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class QuizService {

    private static final Logger logger = LoggerFactory.getLogger(QuizService.class);

    @Autowired
    private QuizRepository quizRepository;

    @Autowired
    private QuizAttemptRepository quizAttemptRepository;

    @Autowired
    private AchievementRepository achievementRepository;

    @Autowired
    private BadgeRepository badgeRepository;

    @Autowired
    private AiService aiService;

    @Autowired
    private ProgressService progressService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final String QUIZ_SYSTEM_PROMPT_TEMPLATE =
            "You are an expert curriculum builder and language testing instructor. " +
            "Generate a language learning quiz covering the topic category '%s' at '%s' difficulty level. " +
            "You MUST generate EXACTLY %d questions. Do not generate more, do not generate less. " +
            "You must include a mix of question types: MCQ (Multiple Choice), TRUE_FALSE, FILL_IN_BLANKS, and MATCH. " +
            "For MCQ, provide 3 to 4 logical options. For TRUE_FALSE, options must be ['True', 'False']. " +
            "For FILL_IN_BLANKS, options must be an empty list. " +
            "Keep the correct answers lowercase for FILL_IN_BLANKS, or exact case-sensitive options for others. " +
            "For MATCH type, options must contain the left-side terms (e.g. [\"Hola\", \"Adiós\", \"Gracias\"]), " +
            "and correctAnswer must contain the mapping of left to right terms in the format \"left1=right1|left2=right2|left3=right3\" " +
            "(e.g. \"Hola=Hello|Adiós=Goodbye|Gracias=Thank you\"). " +
            "You MUST respond ONLY with a JSON object. Do not include markdown code block formatting (like ```json). " +
            "The JSON structure must be exactly as follows:\n" +
            "{\n" +
            "  \"title\": \"[A descriptive and interesting quiz title]\",\n" +
            "  \"description\": \"[A brief description explaining what this quiz tests]\",\n" +
            "  \"questions\": [\n" +
            "    {\n" +
            "      \"id\": \"q1\",\n" +
            "      \"questionText\": \"[Insert question text here]\",\n" +
            "      \"type\": \"MCQ\",\n" +
            "      \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"],\n" +
            "      \"correctAnswer\": \"Option B\",\n" +
            "      \"points\": 10\n" +
            "    }\n" +
            "  ]\n" +
            "}";

    public Quiz generateQuiz(String userId, QuizGenerateRequest request) {
        logger.info("Generating AI quiz for user: {}, topic: {}, level: {}, count: {}", userId, request.getCategory(), request.getDifficulty(), request.getQuestionCount());
        String systemPrompt = String.format(
                QUIZ_SYSTEM_PROMPT_TEMPLATE,
                request.getCategory(),
                request.getDifficulty(),
                request.getQuestionCount()
        );

        String aiResponse = aiService.generateContent(systemPrompt, "Please build the quiz now.");
        String cleaned = cleanJsonString(aiResponse);

        try {
            JsonNode root = objectMapper.readTree(cleaned);
            String title = root.path("title").asText("Practice Quiz - " + request.getCategory());
            String desc = root.path("description").asText("A practice quiz on " + request.getCategory());

            List<Quiz.Question> questions = new ArrayList<>();
            JsonNode questionsArray = root.path("questions");

            if (questionsArray.isArray()) {
                int idCounter = 1;
                for (JsonNode qNode : questionsArray) {
                    List<String> options = new ArrayList<>();
                    JsonNode optsArray = qNode.path("options");
                    if (optsArray.isArray()) {
                        for (JsonNode o : optsArray) {
                            options.add(o.asText());
                        }
                    }

                    // Randomize options for MCQ questions
                    String qType = qNode.path("type").asText("MCQ");
                    if ("MCQ".equalsIgnoreCase(qType)) {
                        Collections.shuffle(options);
                    }

                    questions.add(Quiz.Question.builder()
                            .id("q" + idCounter++)
                            .questionText(qNode.path("questionText").asText(""))
                            .type(qType)
                            .options(options)
                            .correctAnswer(qNode.path("correctAnswer").asText(""))
                            .points(qNode.path("points").asInt(10))
                            .build());
                }
            }

            // Shuffle questions to randomize
            Collections.shuffle(questions);

            Quiz quiz = Quiz.builder()
                    .title(title)
                    .description(desc)
                    .category(request.getCategory())
                    .difficulty(request.getDifficulty())
                    .questions(questions)
                    .timeLimit(Math.max(5, request.getQuestionCount() * 2)) // 2 mins per question, min 5
                    .createdBy("AI")
                    .createdAt(Instant.now())
                    .build();

            return quizRepository.save(quiz);
        } catch (Exception e) {
            logger.error("Failed to parse quiz JSON from AI. Raw response: {}. Error: {}", aiResponse, e.getMessage());
            throw new BadRequestException("AI failed to generate a structured quiz. Please try again. Raw: " + e.getMessage());
        }
    }

    public Quiz getQuizDetails(String quizId) {
        return quizRepository.findById(quizId)
                .orElseThrow(() -> new ResourceNotFoundException("Quiz not found"));
    }

    public QuizSubmitResponse submitQuiz(String quizId, String userId, QuizSubmitRequest request) {
        Quiz quiz = getQuizDetails(quizId);
        logger.info("Grading quiz submission: {} for user: {}", quizId, userId);

        int totalScore = 0;
        int maxScore = 0;
        int correctCount = 0;
        Map<String, String> correctAnswers = new HashMap<>();

        for (Quiz.Question q : quiz.getQuestions()) {
            maxScore += q.getPoints();
            correctAnswers.put(q.getId(), q.getCorrectAnswer());

            String userAns = request.getAnswers().get(q.getId());
            if (userAns != null && isAnswerCorrect(userAns, q.getCorrectAnswer(), q.getType())) {
                totalScore += q.getPoints();
                correctCount++;
            }
        }

        double percentage = maxScore > 0 ? ((double) totalScore / maxScore) * 100.0 : 0.0;
        boolean passed = percentage >= 60.0; // 60% passing rate

        // Save Attempt records
        QuizAttempt attempt = QuizAttempt.builder()
                .userId(userId)
                .quizId(quizId)
                .answers(request.getAnswers())
                .score(totalScore)
                .maxScore(maxScore)
                .percentage(percentage)
                .timeTaken(request.getTimeTaken())
                .completedAt(Instant.now())
                .build();
        quizAttemptRepository.save(attempt);

        // Query current achievements/badges to detect new ones unlocked during the attempt
        List<String> oldAchievements = achievementRepository.findByUserId(userId).stream().map(Achievement::getTitle).collect(Collectors.toList());
        List<String> oldBadges = badgeRepository.findByUserId(userId).stream().map(Badge::getName).collect(Collectors.toList());

        // Record score to user profile and update XP
        progressService.recordQuizScore(userId, totalScore, maxScore);

        // Query new achievements/badges after update
        List<String> newAchievements = achievementRepository.findByUserId(userId).stream().map(Achievement::getTitle).collect(Collectors.toList());
        List<String> newBadges = badgeRepository.findByUserId(userId).stream().map(Badge::getName).collect(Collectors.toList());

        List<String> unlockedAchievements = newAchievements.stream().filter(a -> !oldAchievements.contains(a)).collect(Collectors.toList());
        List<String> unlockedBadges = newBadges.stream().filter(b -> !oldBadges.contains(b)).collect(Collectors.toList());

        return QuizSubmitResponse.builder()
                .attemptId(attempt.getId())
                .quizId(quizId)
                .score(totalScore)
                .maxScore(maxScore)
                .percentage(percentage)
                .correctCount(correctCount)
                .totalCount(quiz.getQuestions().size())
                .passed(passed)
                .xpEarned(totalScore * 2)
                .unlockedBadges(unlockedBadges)
                .unlockedAchievements(unlockedAchievements)
                .correctAnswers(correctAnswers)
                .build();
    }

    public List<QuizAttempt> getAttempts(String userId) {
        return quizAttemptRepository.findByUserIdOrderByCompletedAtDesc(userId);
    }

    public QuizAttempt getAttemptDetails(String attemptId, String userId) {
        QuizAttempt attempt = quizAttemptRepository.findById(attemptId)
                .orElseThrow(() -> new ResourceNotFoundException("Quiz attempt record not found"));

        if (!attempt.getUserId().equals(userId)) {
            throw new BadRequestException("Unauthorized access to attempt records.");
        }
        return attempt;
    }

    private boolean isAnswerCorrect(String userAns, String correctAns, String qType) {
        if (userAns == null || correctAns == null) return false;

        if ("FILL_IN_BLANKS".equalsIgnoreCase(qType)) {
            return userAns.trim().equalsIgnoreCase(correctAns.trim());
        }
        if ("TRUE_FALSE".equalsIgnoreCase(qType)) {
            return userAns.trim().equalsIgnoreCase(correctAns.trim());
        }
        if ("MATCH".equalsIgnoreCase(qType)) {
            Map<String, String> userMap = parseMatchPairs(userAns);
            Map<String, String> correctMap = parseMatchPairs(correctAns);
            return !userMap.isEmpty() && userMap.equals(correctMap);
        }
        return userAns.trim().equalsIgnoreCase(correctAns.trim());
    }

    private Map<String, String> parseMatchPairs(String matchStr) {
        Map<String, String> map = new HashMap<>();
        if (matchStr == null || matchStr.isBlank()) return map;
        String[] pairs = matchStr.split("\\|");
        for (String pair : pairs) {
            String[] kv = pair.split("=");
            if (kv.length == 2) {
                map.put(kv[0].trim().toLowerCase(), kv[1].trim().toLowerCase());
            }
        }
        return map;
    }

    private String cleanJsonString(String response) {
        if (response == null) return "{}";
        response = response.trim();
        if (response.startsWith("```")) {
            int firstLineEnd = response.indexOf('\n');
            if (firstLineEnd != -1) {
                response = response.substring(firstLineEnd);
            }
            if (response.endsWith("```")) {
                response = response.substring(0, response.length() - 3);
            }
        }
        return response.trim();
    }
}
