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
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

@Document(collection = "progress")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Progress {
    @Id
    private String id;

    @Indexed(unique = true)
    private String userId;

    @Builder.Default
    private int streak = 0;

    @Builder.Default
    private int longestStreak = 0;

    @Builder.Default
    private int xp = 0;

    @Builder.Default
    private int level = 1;

    private Instant lastActivityDate;

    @Builder.Default
    private int totalQuizScore = 0;

    @Builder.Default
    private double averageGrammarAccuracy = 100.0;

    @Builder.Default
    private double averageQuizAccuracy = 0.0;

    @Builder.Default
    private int totalTranslations = 0;

    @Builder.Default
    private int totalChats = 0;

    @Builder.Default
    private double totalHours = 0.0;

    @Builder.Default
    private int completedQuizzesCount = 0;

    @Builder.Default
    private Set<String> targetLanguages = new HashSet<>();

    // Stores hours spent or activity intensity per day of the week (e.g. "Monday" -> 1.5)
    @Builder.Default
    private Map<String, Double> weeklyActivity = new HashMap<>();

    // Stores hours spent or activity intensity per week of the month (e.g. "Week 1" -> 5.0)
    @Builder.Default
    private Map<String, Double> monthlyActivity = new HashMap<>();
}
