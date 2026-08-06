package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TranslationResponse {
    private String id;
    private String sourceText;
    private String translatedText;
    private String sourceLanguage;
    private String targetLanguage;
    private boolean isFavorite;
    private Instant createdAt;
}
