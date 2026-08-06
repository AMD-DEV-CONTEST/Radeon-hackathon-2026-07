package com.linguabot.service;

import com.linguabot.model.ChatHistory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

@Service
public class AiService {

    private static final Logger logger = LoggerFactory.getLogger(AiService.class);

    @Autowired(required = false)
    private ChatModel chatModel;

    @org.springframework.beans.factory.annotation.Value("${linguabot.gemini.apiKey:}")
    private String geminiApiKey;

    @org.springframework.beans.factory.annotation.Value("${linguabot.gemini.apiUrl:https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent}")
    private String geminiApiUrl;

    private final org.springframework.web.client.RestTemplate restTemplate = new org.springframework.web.client.RestTemplate();

    private boolean isGeminiEnabled() {
        return geminiApiKey != null && geminiApiKey.trim().startsWith("AIzaSy");
    }

    private String callGeminiApi(String systemInstruction, String userMessage) {
        try {
            java.util.Map<String, Object> requestBody = new java.util.HashMap<>();
            if (systemInstruction != null && !systemInstruction.isBlank()) {
                requestBody.put("systemInstruction", java.util.Map.of(
                    "parts", java.util.List.of(java.util.Map.of("text", systemInstruction))
                ));
            }
            requestBody.put("contents", java.util.List.of(
                java.util.Map.of(
                    "role", "user",
                    "parts", java.util.List.of(java.util.Map.of("text", userMessage))
                )
            ));

            String url = geminiApiUrl.contains("?key=") ? geminiApiUrl : geminiApiUrl + "?key=" + geminiApiKey;
            org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
            headers.setContentType(org.springframework.http.MediaType.APPLICATION_JSON);
            org.springframework.http.HttpEntity<java.util.Map<String, Object>> entity = new org.springframework.http.HttpEntity<>(requestBody, headers);

            org.springframework.http.ResponseEntity<java.util.Map> response = restTemplate.postForEntity(url, entity, java.util.Map.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                java.util.List candidates = (java.util.List) response.getBody().get("candidates");
                if (candidates != null && !candidates.isEmpty()) {
                    java.util.Map candidate = (java.util.Map) candidates.get(0);
                    java.util.Map content = (java.util.Map) candidate.get("content");
                    if (content != null) {
                        java.util.List parts = (java.util.List) content.get("parts");
                        if (parts != null && !parts.isEmpty()) {
                            java.util.Map part = (java.util.Map) parts.get(0);
                            return (String) part.get("text");
                        }
                    }
                }
            }
            throw new RuntimeException("Unexpected response format from Gemini API");
        } catch (Exception e) {
            logger.error("Gemini API call failed: {}", e.getMessage());
            throw new RuntimeException(e);
        }
    }

    private String callGeminiChatApi(String systemInstruction, List<ChatHistory.Message> historyMessages) {
        try {
            java.util.Map<String, Object> requestBody = new java.util.HashMap<>();
            if (systemInstruction != null && !systemInstruction.isBlank()) {
                requestBody.put("systemInstruction", java.util.Map.of(
                    "parts", java.util.List.of(java.util.Map.of("text", systemInstruction))
                ));
            }

            java.util.List<java.util.Map<String, Object>> contents = new java.util.ArrayList<>();
            for (ChatHistory.Message msg : historyMessages) {
                String role = "user".equalsIgnoreCase(msg.getSender()) ? "user" : "model";
                contents.add(java.util.Map.of(
                    "role", role,
                    "parts", java.util.List.of(java.util.Map.of("text", msg.getContent()))
                ));
            }
            requestBody.put("contents", contents);

            String url = geminiApiUrl.contains("?key=") ? geminiApiUrl : geminiApiUrl + "?key=" + geminiApiKey;
            org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
            headers.setContentType(org.springframework.http.MediaType.APPLICATION_JSON);
            org.springframework.http.HttpEntity<java.util.Map<String, Object>> entity = new org.springframework.http.HttpEntity<>(requestBody, headers);

            org.springframework.http.ResponseEntity<java.util.Map> response = restTemplate.postForEntity(url, entity, java.util.Map.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                java.util.List candidates = (java.util.List) response.getBody().get("candidates");
                if (candidates != null && !candidates.isEmpty()) {
                    java.util.Map candidate = (java.util.Map) candidates.get(0);
                    java.util.Map content = (java.util.Map) candidate.get("content");
                    if (content != null) {
                        java.util.List parts = (java.util.List) content.get("parts");
                        if (parts != null && !parts.isEmpty()) {
                            java.util.Map part = (java.util.Map) parts.get(0);
                            return (String) part.get("text");
                        }
                    }
                }
            }
            throw new RuntimeException("Unexpected response format from Gemini API");
        } catch (Exception e) {
            logger.error("Gemini Chat API call failed: {}", e.getMessage());
            throw new RuntimeException(e);
        }
    }

    private Flux<String> streamGeminiChatReply(String systemInstruction, List<ChatHistory.Message> historyMessages) {
        String fullReply = callGeminiChatApi(systemInstruction, historyMessages);
        String[] words = fullReply.split("(?<=\\s)");
        return Flux.fromArray(words)
                .delayElements(Duration.ofMillis(30));
    }

    /**
     * Generates content using system instruction and user message.
     */
    public String generateContent(String systemInstruction, String userMessage) {
        if (isGeminiEnabled()) {
            try {
                logger.info("Using Google Gemini HTTP API for content generation.");
                return callGeminiApi(systemInstruction, userMessage);
            } catch (Exception e) {
                logger.warn("Gemini API call failed, falling back: {}", e.getMessage());
            }
        }

        if (chatModel == null) {
            logger.warn("ChatModel is not configured. Returning local simulated response.");
            return getSimulatedContent(systemInstruction, userMessage);
        }

        try {
            List<Message> messages = new ArrayList<>();
            if (systemInstruction != null && !systemInstruction.isBlank()) {
                messages.add(new SystemMessage(systemInstruction));
            }
            messages.add(new UserMessage(userMessage));

            Prompt prompt = new Prompt(messages);
            logger.debug("Calling ChatModel for content generation.");
            return chatModel.call(prompt).getResult().getOutput().getContent();
        } catch (Exception e) {
            logger.error("Error communicating with OpenAI (using local fallback): {}", e.getMessage());
            return getSimulatedContent(systemInstruction, userMessage);
        }
    }

    /**
     * Generates a reply in a conversational context given a list of previous chat messages.
     */
    public String generateChatReply(String systemInstruction, List<ChatHistory.Message> historyMessages) {
        if (isGeminiEnabled()) {
            try {
                logger.info("Using Google Gemini HTTP API for chat reply.");
                return callGeminiChatApi(systemInstruction, historyMessages);
            } catch (Exception e) {
                logger.warn("Gemini Chat API call failed, falling back: {}", e.getMessage());
            }
        }

        if (chatModel == null) {
            logger.warn("ChatModel is not configured. Returning local simulated response.");
            return getSimulatedChatReply(historyMessages);
        }

        try {
            List<Message> messages = new ArrayList<>();
            if (systemInstruction != null && !systemInstruction.isBlank()) {
                messages.add(new SystemMessage(systemInstruction));
            }

            for (ChatHistory.Message msg : historyMessages) {
                if ("user".equalsIgnoreCase(msg.getSender())) {
                    messages.add(new UserMessage(msg.getContent()));
                } else {
                    messages.add(new AssistantMessage(msg.getContent()));
                }
            }

            Prompt prompt = new Prompt(messages);
            logger.debug("Calling ChatModel for chat reply.");
            return chatModel.call(prompt).getResult().getOutput().getContent();
        } catch (Exception e) {
            logger.error("Error communicating with OpenAI (using local fallback): {}", e.getMessage());
            return getSimulatedChatReply(historyMessages);
        }
    }

    /**
     * Streams a reply in a conversational context.
     */
    public Flux<String> streamChatReply(String systemInstruction, List<ChatHistory.Message> historyMessages) {
        if (isGeminiEnabled()) {
            try {
                logger.info("Using Google Gemini HTTP API for streaming chat reply.");
                return streamGeminiChatReply(systemInstruction, historyMessages);
            } catch (Exception e) {
                logger.warn("Gemini streaming call failed, falling back: {}", e.getMessage());
            }
        }

        if (chatModel == null) {
            logger.warn("ChatModel is not configured. Returning local simulated stream.");
            return streamSimulatedChatReply(historyMessages);
        }

        try {
            List<Message> messages = new ArrayList<>();
            if (systemInstruction != null && !systemInstruction.isBlank()) {
                messages.add(new SystemMessage(systemInstruction));
            }

            for (ChatHistory.Message msg : historyMessages) {
                if ("user".equalsIgnoreCase(msg.getSender())) {
                    messages.add(new UserMessage(msg.getContent()));
                } else {
                    messages.add(new AssistantMessage(msg.getContent()));
                }
            }

            Prompt prompt = new Prompt(messages);
            logger.debug("Initiating ChatModel reply stream.");
            return chatModel.stream(prompt)
                    .map(response -> {
                        if (response.getResult() != null && response.getResult().getOutput() != null) {
                            String text = response.getResult().getOutput().getContent();
                            return text != null ? text : "";
                        }
                        return "";
                    })
                    .onErrorResume(throwable -> {
                        logger.error("Error in OpenAI stream subscription (using local fallback): {}", throwable.getMessage());
                        return streamSimulatedChatReply(historyMessages);
                    });
        } catch (Exception e) {
            logger.error("Error communicating with OpenAI (using local fallback stream): {}", e.getMessage());
            return streamSimulatedChatReply(historyMessages);
        }
    }

    /* =========================================================================
       LOCAL AI SIMULATION FALLBACK ENGINE (Activated on 429/401 API limits)
       ========================================================================= */

    private String getSimulatedContent(String systemInstruction, String userMessage) {
        // 1. Detect Quiz Generation request
        if (systemInstruction != null && systemInstruction.contains("You must include a mix of question types")) {
            int count = 5;
            if (systemInstruction.contains("10")) count = 10;
            if (systemInstruction.contains("15")) count = 15;
            return getMockQuizJson(count);
        }

        // 2. Detect Grammar Audit request
        if (systemInstruction != null && systemInstruction.contains("Analyze the user's input text for grammar")) {
            return getMockGrammarJson(userMessage);
        }

        // 3. Detect Translation request
        if (systemInstruction != null && systemInstruction.contains("Translate the user's input text")) {
            return getMockTranslationJson(userMessage);
        }

        return "AI Simulator: I am here as your tutor helper. Please type a message to practice.";
    }

    private String getSimulatedChatReply(List<ChatHistory.Message> historyMessages) {
        if (historyMessages.isEmpty()) {
            return "Bonjour! I am LinguaBot, your language tutor. How can I help you learn today?";
        }
        
        String lastUserMsg = historyMessages.get(historyMessages.size() - 1).getContent().toLowerCase();
        
        if (lastUserMsg.contains("bonjour") || lastUserMsg.contains("merci")) {
            return "Bonjour! **Bonjour** means \"Hello\" and **merci** means \"Thank you\" in French. Excellent vocabulary start! How else can I assist you?";
        }
        
        if (lastUserMsg.contains("quicksort") || lastUserMsg.contains("python") || lastUserMsg.contains("code")) {
            return "Here is a quick example of a **Quicksort** algorithm written in Python:\n\n" +
                   "```python\n" +
                   "def quicksort(arr):\n" +
                   "    if len(arr) <= 1:\n" +
                   "        return arr\n" +
                   "    pivot = arr[len(arr) // 2]\n" +
                   "    left = [x for x in arr if x < pivot]\n" +
                   "    middle = [x for x in arr if x == pivot]\n" +
                   "    right = [x for x in arr if x > pivot]\n" +
                   "    return quicksort(left) + middle + quicksort(right)\n" +
                   "\n" +
                   "print(quicksort([3,6,8,10,1,2,1]))\n" +
                   "```\n\n" +
                   "Let me know if you need this explained in detail!";
        }

        return "I received your request: \"" + lastUserMsg + "\". Let's continue practicing vocabulary or conversational grammar. Feel free to ask me to explain grammar rules!";
    }

    private Flux<String> streamSimulatedChatReply(List<ChatHistory.Message> historyMessages) {
        String fullReply = getSimulatedChatReply(historyMessages);
        // Split reply into small chunks and emit with a slight delay to simulate typing
        String[] words = fullReply.split("(?<=\\s)");
        return Flux.fromArray(words)
                .delayElements(Duration.ofMillis(80));
    }

    private String getMockQuizJson(int count) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append("  \"title\": \"Practice Quiz - AI Language Immersion\",\n");
        sb.append("  \"description\": \"A practice quiz testing your vocabulary, pronouns, and verbs across French, Spanish, German, and Italian.\",\n");
        sb.append("  \"questions\": [\n");

        List<String> allQuestions = new ArrayList<>();
        // Q1
        allQuestions.add("    {\n" +
                "      \"id\": \"q1\",\n" +
                "      \"questionText\": \"What is the correct translation of 'Thank you very much' in French?\",\n" +
                "      \"type\": \"MCQ\",\n" +
                "      \"options\": [\"Merci beaucoup\", \"S'il vous plaît\", \"Bonjour\", \"Au revoir\"],\n" +
                "      \"correctAnswer\": \"Merci beaucoup\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q2
        allQuestions.add("    {\n" +
                "      \"id\": \"q2\",\n" +
                "      \"questionText\": \"True or False: In French, adjectives always come before the noun they modify.\",\n" +
                "      \"type\": \"TRUE_FALSE\",\n" +
                "      \"options\": [\"True\", \"False\"],\n" +
                "      \"correctAnswer\": \"False\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q3
        allQuestions.add("    {\n" +
                "      \"id\": \"q3\",\n" +
                "      \"questionText\": \"Complete the sentence: 'Je ___ un étudiant' (I am a student).\",\n" +
                "      \"type\": \"FILL_IN_BLANKS\",\n" +
                "      \"options\": [],\n" +
                "      \"correctAnswer\": \"suis\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q4
        allQuestions.add("    {\n" +
                "      \"id\": \"q4\",\n" +
                "      \"questionText\": \"Match the corresponding English and French pronouns:\",\n" +
                "      \"type\": \"MATCH\",\n" +
                "      \"options\": [\"I\", \"You\", \"We\", \"They\"],\n" +
                "      \"correctAnswer\": \"I=Je|You=Tu|We=Nous|They=Ils\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q5
        allQuestions.add("    {\n" +
                "      \"id\": \"q5\",\n" +
                "      \"questionText\": \"Select the word that represents the number '8' in Spanish:\",\n" +
                "      \"type\": \"MCQ\",\n" +
                "      \"options\": [\"Cinco\", \"Siete\", \"Ocho\", \"Nueve\"],\n" +
                "      \"correctAnswer\": \"Ocho\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q6
        allQuestions.add("    {\n" +
                "      \"id\": \"q6\",\n" +
                "      \"questionText\": \"How do you say 'Where is the bathroom?' in Spanish?\",\n" +
                "      \"type\": \"MCQ\",\n" +
                "      \"options\": [\"¿Dónde está el baño?\", \"¿Qué hora es?\", \"Mucho gusto\", \"Buenas noches\"],\n" +
                "      \"correctAnswer\": \"¿Dónde está el baño?\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q7
        allQuestions.add("    {\n" +
                "      \"id\": \"q7\",\n" +
                "      \"questionText\": \"True or False: In Spanish, 'Hola' means goodbye.\",\n" +
                "      \"type\": \"TRUE_FALSE\",\n" +
                "      \"options\": [\"True\", \"False\"],\n" +
                "      \"correctAnswer\": \"False\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q8
        allQuestions.add("    {\n" +
                "      \"id\": \"q8\",\n" +
                "      \"questionText\": \"Complete the Spanish sentence: 'Yo ___ de Madrid' (I am from Madrid - permanent quality).\",\n" +
                "      \"type\": \"FILL_IN_BLANKS\",\n" +
                "      \"options\": [],\n" +
                "      \"correctAnswer\": \"soy\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q9
        allQuestions.add("    {\n" +
                "      \"id\": \"q9\",\n" +
                "      \"questionText\": \"Match the corresponding English and Spanish greetings:\",\n" +
                "      \"type\": \"MATCH\",\n" +
                "      \"options\": [\"Hello\", \"Good morning\", \"Good afternoon\", \"Good night\"],\n" +
                "      \"correctAnswer\": \"Hello=Hola|Good morning=Buenos días|Good afternoon=Buenas tardes|Good night=Buenas noches\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q10
        allQuestions.add("    {\n" +
                "      \"id\": \"q10\",\n" +
                "      \"questionText\": \"How do you say 'Please' in German?\",\n" +
                "      \"type\": \"MCQ\",\n" +
                "      \"options\": [\"Bitte\", \"Danke\", \"Hallo\", \"Tschüss\"],\n" +
                "      \"correctAnswer\": \"Bitte\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q11
        allQuestions.add("    {\n" +
                "      \"id\": \"q11\",\n" +
                "      \"questionText\": \"True or False: In German, 'Danke' means thank you.\",\n" +
                "      \"type\": \"TRUE_FALSE\",\n" +
                "      \"options\": [\"True\", \"False\"],\n" +
                "      \"correctAnswer\": \"True\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q12
        allQuestions.add("    {\n" +
                "      \"id\": \"q12\",\n" +
                "      \"questionText\": \"Complete the German sentence: 'Ich ___ ein Buch' (I read a book).\",\n" +
                "      \"type\": \"FILL_IN_BLANKS\",\n" +
                "      \"options\": [],\n" +
                "      \"correctAnswer\": \"lese\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q13
        allQuestions.add("    {\n" +
                "      \"id\": \"q13\",\n" +
                "      \"questionText\": \"Match the corresponding English and German pronouns:\",\n" +
                "      \"type\": \"MATCH\",\n" +
                "      \"options\": [\"I\", \"You\", \"He\", \"She\"],\n" +
                "      \"correctAnswer\": \"I=Ich|You=Du|He=Er|She=Sie\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q14
        allQuestions.add("    {\n" +
                "      \"id\": \"q14\",\n" +
                "      \"questionText\": \"What is the Italian word for 'Water'?\",\n" +
                "      \"type\": \"MCQ\",\n" +
                "      \"options\": [\"Acqua\", \"Pane\", \"Vino\", \"Latte\"],\n" +
                "      \"correctAnswer\": \"Acqua\",\n" +
                "      \"points\": 10\n" +
                "    }");
        // Q15
        allQuestions.add("    {\n" +
                "      \"id\": \"q15\",\n" +
                "      \"questionText\": \"True or False: In Italian, 'Ciao' can mean both hello and goodbye.\",\n" +
                "      \"type\": \"TRUE_FALSE\",\n" +
                "      \"options\": [\"True\", \"False\"],\n" +
                "      \"correctAnswer\": \"True\",\n" +
                "      \"points\": 10\n" +
                "    }");

        int limit = Math.min(count, allQuestions.size());
        for (int i = 0; i < limit; i++) {
            sb.append(allQuestions.get(i));
            if (i < limit - 1) {
                sb.append(",\n");
            }
        }

        sb.append("\n  ]\n");
        sb.append("}");
        return sb.toString();
    }

    private String getMockGrammarJson(String originalText) {
        String corrected = originalText;
        List<String> mistakesList = new ArrayList<>();

        if (originalText.toLowerCase().contains("has goes")) {
            corrected = corrected.replace("has goes", "went");
            mistakesList.add("{\"mistake\":\"has goes\",\"correction\":\"went\",\"explanation\":\"In English, the past tense of 'go' is 'went'. 'Has goes' is grammatically incorrect.\"}");
        }
        if (originalText.toLowerCase().contains("buyed")) {
            corrected = corrected.replace("buyed", "buy");
            mistakesList.add("{\"mistake\":\"buyed\",\"correction\":\"buy\",\"explanation\":\"The infinitive form of the verb after 'to' should be used. The correct verb is 'buy', not 'buyed'.\"}");
        }
        if (originalText.toLowerCase().contains("i ")) {
            corrected = corrected.replace("i ", "I ");
            mistakesList.add("{\"mistake\":\"i\",\"correction\":\"I\",\"explanation\":\"The personal pronoun 'I' must always be capitalized in English.\"}");
        }
        if (originalText.toLowerCase().contains("apple") && !originalText.toLowerCase().contains("apples")) {
            corrected = corrected.replace("apple", "apples");
            mistakesList.add("{\"mistake\":\"apple\",\"correction\":\"apples\",\"explanation\":\"Since you referred to 'some' apples, the noun should be pluralized.\"}");
        }

        if (corrected.length() > 0 && Character.isLowerCase(corrected.charAt(0))) {
            corrected = Character.toUpperCase(corrected.charAt(0)) + corrected.substring(1);
        }

        StringBuilder sb = new StringBuilder();
        sb.append("{\n");
        sb.append(String.format("  \"correctedText\": \"%s\",\n", corrected));
        sb.append("  \"explanations\": [\n");
        for (int i = 0; i < mistakesList.size(); i++) {
            sb.append("    ").append(mistakesList.get(i));
            if (i < mistakesList.size() - 1) {
                sb.append(",\n");
            }
        }
        sb.append("\n  ]\n");
        sb.append("}");
        return sb.toString();
    }

    private String getMockTranslationJson(String originalText) {
        String detected = "English";
        String translated = originalText;

        if (originalText.toLowerCase().contains("bonjour")) {
            detected = "French";
            translated = "Hello / Good morning";
        } else if (originalText.toLowerCase().contains("excited to practice")) {
            detected = "English";
            translated = "おはようございます！今日は語学力を練習できるのをとても楽しみにしています。";
        } else {
            translated = "Simulated translation: [ " + originalText + " ]";
        }

        return "{\n" +
                "  \"detectedLanguage\": \"" + detected + "\",\n" +
                "  \"translatedText\": \"" + translated + "\"\n" +
                "}";
    }
}
