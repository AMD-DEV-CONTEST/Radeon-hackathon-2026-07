package com.linguabot.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class TranslationRequest {
    @NotBlank(message = "Text to translate cannot be empty")
    private String text;

    @NotBlank(message = "Target language is required")
    private String targetLanguage;

    @NotBlank(message = "Source language setting is required")
    private String sourceLanguage; // "Auto-Detect" or a specific language
}
