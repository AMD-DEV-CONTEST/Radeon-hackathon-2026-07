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

@Document(collection = "quizzes")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Quiz {
    @Id
    private String id;

    private String title;
    private String description;
    
    @Indexed
    private String category; // e.g. "Grammar", "Vocabulary"
    
    @Indexed
    private String difficulty; // e.g. "Easy", "Medium", "Hard"

    @Builder.Default
    private List<Question> questions = new ArrayList<>();

    @Builder.Default
    private int timeLimit = 10; // in minutes

    @CreatedDate
    private Instant createdAt;

    private String createdBy; // "system", "AI", or admin user ID

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Question {
        private String id;
        private String questionText;
        private String type; // "MCQ", "TRUE_FALSE", "FILL_IN_BLANKS"
        
        @Builder.Default
        private List<String> options = new ArrayList<>(); // Empty for Fill in Blanks
        
        private String correctAnswer;
        
        @Builder.Default
        private int points = 10;
    }
}
