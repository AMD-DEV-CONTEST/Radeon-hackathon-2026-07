package com.linguabot.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.linguabot.dto.TranslationRequest;
import com.linguabot.dto.TranslationResponse;
import com.linguabot.exception.BadRequestException;
import com.linguabot.exception.ResourceNotFoundException;
import com.linguabot.model.TranslationHistory;
import com.linguabot.repository.TranslationHistoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;

@Service
public class TranslationService {

    private static final Logger logger = LoggerFactory.getLogger(TranslationService.class);

    @Autowired
    private TranslationHistoryRepository translationHistoryRepository;

    @Autowired
    private AiService aiService;

    @Autowired
    private ProgressService progressService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final String TRANSLATE_SYSTEM_PROMPT_TEMPLATE =
            "You are an expert language translator. " +
            "Translate the user's input text from '%s' into '%s'. " +
            "If the source language is 'Auto-Detect', analyze the text and detect the language first. " +
            "Do not add any explanations or conversations. " +
            "You MUST respond ONLY with a JSON object. Do not include markdown code block formatting (like ```json). " +
            "The JSON structure must be exactly as follows:\n" +
            "{\n" +
            "  \"detectedLanguage\": \"[Detected source language name, e.g. Spanish]\",\n" +
            "  \"translatedText\": \"[Insert complete translated text here]\"\n" +
            "}";

    public TranslationResponse translate(String userId, TranslationRequest request) {
        logger.info("Translating text for user: {}, target language: {}", userId, request.getTargetLanguage());
        String systemPrompt = String.format(
                TRANSLATE_SYSTEM_PROMPT_TEMPLATE,
                request.getSourceLanguage(),
                request.getTargetLanguage()
        );

        String aiResponse = aiService.generateContent(systemPrompt, request.getText());
        String cleaned = cleanJsonString(aiResponse);

        String detectedLang = "Auto-Detect".equals(request.getSourceLanguage()) ? "Unknown" : request.getSourceLanguage();
        String translated = request.getText();

        try {
            JsonNode root = objectMapper.readTree(cleaned);
            detectedLang = root.path("detectedLanguage").asText(detectedLang);
            translated = root.path("translatedText").asText(translated);
        } catch (Exception e) {
            logger.error("Failed to parse translation JSON from AI. Raw response: {}. Error: {}", aiResponse, e.getMessage());
            // If JSON fails, use the raw response text directly as translated text fallback
            translated = aiResponse;
        }

        // Persist translation in user's history
        TranslationHistory history = TranslationHistory.builder()
                .userId(userId)
                .sourceText(request.getText())
                .translatedText(translated)
                .sourceLanguage(detectedLang)
                .targetLanguage(request.getTargetLanguage())
                .isFavorite(false)
                .createdAt(Instant.now())
                .build();
        translationHistoryRepository.save(history);

        // Update statistics log
        progressService.incrementTranslations(userId);

        return mapToResponse(history);
    }

    public List<TranslationHistory> getHistory(String userId) {
        return translationHistoryRepository.findByUserIdOrderByCreatedAtDesc(userId);
    }

    public List<TranslationHistory> getFavorites(String userId) {
        return translationHistoryRepository.findByUserIdAndIsFavoriteOrderByCreatedAtDesc(userId, true);
    }

    public TranslationResponse toggleFavorite(String translationId, String userId) {
        TranslationHistory item = translationHistoryRepository.findById(translationId)
                .orElseThrow(() -> new ResourceNotFoundException("Translation history item not found"));

        if (!item.getUserId().equals(userId)) {
            throw new BadRequestException("Unauthorized access to translation history.");
        }

        item.setFavorite(!item.isFavorite());
        translationHistoryRepository.save(item);
        logger.info("Toggled favorite status for translation: {}", translationId);

        return mapToResponse(item);
    }

    public void deleteTranslation(String translationId, String userId) {
        TranslationHistory item = translationHistoryRepository.findById(translationId)
                .orElseThrow(() -> new ResourceNotFoundException("Translation history item not found"));

        if (!item.getUserId().equals(userId)) {
            throw new BadRequestException("Unauthorized access to translation history.");
        }

        translationHistoryRepository.delete(item);
        logger.info("Translation history item {} deleted successfully", translationId);
    }

    private TranslationResponse mapToResponse(TranslationHistory item) {
        return TranslationResponse.builder()
                .id(item.getId())
                .sourceText(item.getSourceText())
                .translatedText(item.getTranslatedText())
                .sourceLanguage(item.getSourceLanguage())
                .targetLanguage(item.getTargetLanguage())
                .isFavorite(item.isFavorite())
                .createdAt(item.getCreatedAt())
                .build();
    }

    private String cleanJsonString(String response) {
        if (response == null) return "{}";
        response = response.trim();
        if (response.startsWith("```")) {
            int firstLineEnd = response.indexOf('\n');
            if (firstLineEnd != -1) {
                response = response.substring(firstLineEnd);
            }
            if (response.endsWith("```")) {
                response = response.substring(0, response.length() - 3);
            }
        }
        return response.trim();
    }
}
