package com.linguabot.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;

@Document(collection = "badges")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Badge {
    @Id
    private String id;

    @Indexed
    private String userId;

    private String name; // e.g. "Bronze", "Silver", "Gold", "Diamond", "Legend"
    private String description;
    private Instant earnedAt;
}
