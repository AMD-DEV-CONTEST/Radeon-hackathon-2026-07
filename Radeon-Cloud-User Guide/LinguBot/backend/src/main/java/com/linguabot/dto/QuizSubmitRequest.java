package com.linguabot.dto;

import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class QuizSubmitRequest {
    @NotNull(message = "Answers map cannot be null")
    private Map<String, String> answers; // questionId -> userSelectedAnswer

    private int timeTaken; // in seconds
}
