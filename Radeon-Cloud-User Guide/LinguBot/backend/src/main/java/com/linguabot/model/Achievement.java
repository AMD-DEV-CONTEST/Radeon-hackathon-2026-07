package com.linguabot.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;

@Document(collection = "achievements")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Achievement {
    @Id
    private String id;

    @Indexed
    private String userId;

    private String title;
    private String description;
    private String badgeIcon; // e.g. "Flame", "Globe", "Award", "BookOpen", "Clock"

    @CreatedDate
    private Instant unlockedAt;
}
