package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AdminStatsResponse {
    private long totalUsers;
    private double totalHoursSum;
    private long totalQuizzesGenerated;
    private long totalFeedbackSubmitted;
    private double averageStreak;
}
