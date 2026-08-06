package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class QuizSubmitResponse {
    private String attemptId;
    private String quizId;
    private int score;
    private int maxScore;
    private double percentage;
    private int correctCount;
    private int totalCount;
    private boolean passed;
    private int xpEarned;
    private java.util.List<String> unlockedBadges;
    private java.util.List<String> unlockedAchievements;
    private Map<String, String> correctAnswers; // questionId -> correctAnswer
}
