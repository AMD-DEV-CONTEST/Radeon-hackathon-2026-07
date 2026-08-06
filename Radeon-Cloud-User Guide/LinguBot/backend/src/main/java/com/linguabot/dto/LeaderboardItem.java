package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class LeaderboardItem {
    private String userId;
    private String username;
    private int streak;
    private int totalQuizScore;
    private double totalHours;
    private int rank;
}
