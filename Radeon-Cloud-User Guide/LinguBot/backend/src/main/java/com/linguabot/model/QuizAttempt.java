package com.linguabot.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@Document(collection = "quiz_attempts")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class QuizAttempt {
    @Id
    private String id;

    @Indexed
    private String userId;

    @Indexed
    private String quizId;

    // questionId -> userSelectedAnswer
    @Builder.Default
    private Map<String, String> answers = new HashMap<>();

    private int score;
    private int maxScore;
    private double percentage;
    private int timeTaken; // in seconds
    private Instant completedAt;
}
