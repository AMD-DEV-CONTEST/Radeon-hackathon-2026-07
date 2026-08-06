package com.linguabot.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;

@Document(collection = "xp_history")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class XPHistory {
    @Id
    private String id;

    @Indexed
    private String userId;

    private int xpEarned;
    private String activityType; // e.g. "QUIZ", "CHAT", "GRAMMAR", "TRANSLATION", "ACHIEVEMENT"
    private String description;
    private Instant createdAt;
}
