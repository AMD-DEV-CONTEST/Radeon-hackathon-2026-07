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

@Document(collection = "translation_history")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TranslationHistory {
    @Id
    private String id;

    @Indexed
    private String userId;

    private String sourceText;
    private String translatedText;
    private String sourceLanguage;
    private String targetLanguage;

    @Builder.Default
    private boolean isFavorite = false;

    @CreatedDate
    private Instant createdAt;
}
