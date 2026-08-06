package com.linguabot.dto;

import com.linguabot.model.Achievement;
import com.linguabot.model.Badge;
import com.linguabot.model.Progress;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ProgressDetailsResponse {
    private Progress progress;
    private List<Achievement> achievements;
    private List<Badge> badges;
    private List<LeaderboardItem> leaderboard;
    private boolean certificateEligible;
}
