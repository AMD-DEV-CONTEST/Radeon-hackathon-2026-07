package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DashboardResponse {
    private String username;
    private int streak;
    private int xp;
    private int level;
    private int totalQuizScore;
    private int completedQuizzesCount;
    private double averageGrammarAccuracy;
    private int totalTranslations;
    private int totalChats;
    private double totalHours;
    private Map<String, Double> weeklyActivity;
    private Map<String, Double> monthlyActivity;
    private List<ActivityDto> recentActivities;
}
