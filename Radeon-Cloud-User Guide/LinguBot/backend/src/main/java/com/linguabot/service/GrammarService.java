package com.linguabot.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.linguabot.dto.GrammarRequest;
import com.linguabot.dto.GrammarResponse;
import com.linguabot.model.GrammarHistory;
import com.linguabot.repository.GrammarHistoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

@Service
public class GrammarService {

    private static final Logger logger = LoggerFactory.getLogger(GrammarService.class);

    @Autowired
    private GrammarHistoryRepository grammarHistoryRepository;

    @Autowired
    private AiService aiService;

    @Autowired
    private ProgressService progressService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final String GRAMMAR_SYSTEM_PROMPT_TEMPLATE =
            "You are an expert grammar editor and language tutor. " +
            "Analyze the user's input text for grammar, punctuation, vocabulary choice, and spelling. " +
            "Correct the mistakes and rewrite the text to match a %s tone. " +
            "You MUST respond ONLY with a JSON object. Do not include markdown code block formatting (like ```json). " +
            "The JSON structure must be exactly as follows:\n" +
            "{\n" +
            "  \"correctedText\": \"[Insert complete corrected text here]\",\n" +
            "  \"explanations\": [\n" +
            "    {\n" +
            "      \"mistake\": \"[Specify original incorrect word/phrase]\",\n" +
            "      \"correction\": \"[Specify corrected word/phrase]\",\n" +
            "      \"explanation\": \"[Provide a brief, clear explanation of why this was incorrect and how to fix it]\"\n" +
            "    }\n" +
            "  ]\n" +
            "}\n" +
            "If the input text is already grammatically perfect in the requested tone, return the same text as " +
            "\"correctedText\" and leave the \"explanations\" array empty.";

    public GrammarResponse checkGrammar(String userId, GrammarRequest request) {
        String systemPrompt = String.format(GRAMMAR_SYSTEM_PROMPT_TEMPLATE, request.getTone());
        logger.info("Submitting grammar check for user: {}, Tone: {}", userId, request.getTone());
        
        String aiResponse = aiService.generateContent(systemPrompt, request.getText());
        GrammarResponse responseDto = parseAiResponse(request.getText(), request.getTone(), aiResponse);

        // Save correction to database history
        GrammarHistory history = GrammarHistory.builder()
                .userId(userId)
                .originalText(request.getText())
                .correctedText(responseDto.getCorrectedText())
                .tone(request.getTone())
                .explanations(responseDto.getExplanations())
                .createdAt(Instant.now())
                .build();
        grammarHistoryRepository.save(history);

        // Calculate statistics and log progress hours
        int wordCount = request.getText().trim().split("\\s+").length;
        progressService.recordGrammarCheck(userId, responseDto.getExplanations().size(), wordCount);

        return responseDto;
    }

    public List<GrammarHistory> getHistory(String userId) {
        return grammarHistoryRepository.findByUserIdOrderByCreatedAtDesc(userId);
    }

    private GrammarResponse parseAiResponse(String originalText, String tone, String rawResponse) {
        String cleaned = cleanJsonString(rawResponse);
        try {
            JsonNode root = objectMapper.readTree(cleaned);
            String corrected = root.path("correctedText").asText(originalText);
            
            List<GrammarHistory.ExplanationItem> explanations = new ArrayList<>();
            JsonNode explanationArray = root.path("explanations");
            if (explanationArray.isArray()) {
                for (JsonNode node : explanationArray) {
                    explanations.add(GrammarHistory.ExplanationItem.builder()
                            .mistake(node.path("mistake").asText(""))
                            .correction(node.path("correction").asText(""))
                            .explanation(node.path("explanation").asText(""))
                            .build());
                }
            }

            return GrammarResponse.builder()
                    .originalText(originalText)
                    .correctedText(corrected)
                    .explanations(explanations)
                    .tone(tone)
                    .build();
        } catch (Exception e) {
            logger.error("Failed to parse grammar JSON from AI. Raw response: {}. Error: {}", rawResponse, e.getMessage());
            // Fallback response mapping
            return GrammarResponse.builder()
                    .originalText(originalText)
                    .correctedText(originalText)
                    .explanations(new ArrayList<>())
                    .tone(tone)
                    .build();
        }
    }

    private String cleanJsonString(String response) {
        if (response == null) return "{}";
        response = response.trim();
        if (response.startsWith("```")) {
            // Strip starting block (e.g. ```json or ```)
            int firstLineEnd = response.indexOf('\n');
            if (firstLineEnd != -1) {
                response = response.substring(firstLineEnd);
            }
            // Strip ending block (e.g. ```)
            if (response.endsWith("```")) {
                response = response.substring(0, response.length() - 3);
            }
        }
        return response.trim();
    }
}
