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
import java.util.ArrayList;
import java.util.List;

@Document(collection = "grammar_history")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GrammarHistory {
    @Id
    private String id;

    @Indexed
    private String userId;

    private String originalText;
    private String correctedText;
    
    @Builder.Default
    private List<ExplanationItem> explanations = new ArrayList<>();
    
    private String tone; // e.g. "Formal", "Professional", "Casual"

    @CreatedDate
    private Instant createdAt;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class ExplanationItem {
        private String mistake;
        private String correction;
        private String explanation;
    }
}
