package com.linguabot.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class QuizGenerateRequest {
    @NotBlank(message = "Category topic is required")
    private String category; // e.g. "Grammar", "Vocabulary", "Verbs", "Greetings"

    @NotBlank(message = "Difficulty level is required")
    private String difficulty; // "Easy", "Medium", "Hard"

    @Min(value = 3, message = "Quiz must contain at least 3 questions")
    @Max(value = 15, message = "Quiz can contain at most 15 questions")
    private int questionCount = 5;
}
