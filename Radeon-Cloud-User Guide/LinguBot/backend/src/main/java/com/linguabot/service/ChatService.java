package com.linguabot.service;

import com.linguabot.dto.ChatSessionResponse;
import com.linguabot.dto.MessageRequest;
import com.linguabot.exception.BadRequestException;
import com.linguabot.exception.ResourceNotFoundException;
import com.linguabot.model.ChatHistory;
import com.linguabot.repository.ChatHistoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.time.Instant;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class ChatService {

    private static final Logger logger = LoggerFactory.getLogger(ChatService.class);

    @Autowired
    private ChatHistoryRepository chatHistoryRepository;

    @Autowired
    private AiService aiService;

    @Autowired
    private ProgressService progressService;

    private static final String CHATBOT_SYSTEM_PROMPT = 
            "You are LinguaBot.\n" +
            "You are an expert language tutor.\n" +
            "You teach grammar.\n" +
            "Translate.\n" +
            "Explain vocabulary.\n" +
            "Explain pronunciation.\n" +
            "Generate quizzes.\n" +
            "Answer general questions.\n" +
            "If user asks programming, answer correctly.\n" +
            "If user asks mathematics, answer correctly.\n" +
            "If user asks science, answer correctly.\n" +
            "Never repeat responses.\n" +
            "Always analyze context.\n" +
            "Use previous conversation.\n" +
            "Answer naturally.\n" +
            "If the user makes grammatical errors in their message, gently point them out and suggest the correct way to say it at the very end of your response inside a blockquote, like: \n" +
            "> *Correction:* [Your correction here] - [Simple explanation].";

    public ChatHistory renameChatSession(String sessionId, String userId, String newTitle) {
        ChatHistory chat = getChatSessionDetails(sessionId, userId);
        chat.setSessionTitle(newTitle);
        chat.setUpdatedAt(Instant.now());
        logger.info("Renaming chat session {} to: {}", sessionId, newTitle);
        return chatHistoryRepository.save(chat);
    }

    public Flux<String> sendMessageStream(String sessionId, String userId, MessageRequest request) {
        ChatHistory chat = getChatSessionDetails(sessionId, userId);

        // Append user message
        ChatHistory.Message userMsg = ChatHistory.Message.builder()
                .sender("user")
                .content(request.getContent())
                .timestamp(Instant.now())
                .build();
        chat.getMessages().add(userMsg);

        // Auto-summarize first message to set a clean session title
        if ("New Conversation".equals(chat.getSessionTitle())) {
            String title = generateTitleFromMessage(request.getContent());
            chat.setSessionTitle(title);
        }

        chat.setUpdatedAt(Instant.now());
        chatHistoryRepository.save(chat);

        // Update learning progress
        progressService.incrementChats(userId);

        StringBuilder fullReply = new StringBuilder();
        return aiService.streamChatReply(CHATBOT_SYSTEM_PROMPT, chat.getMessages())
                .doOnNext(fullReply::append)
                .doOnComplete(() -> {
                    // Fetch the latest state to avoid race conditions
                    ChatHistory freshChat = chatHistoryRepository.findById(sessionId).orElse(chat);
                    ChatHistory.Message botMsg = ChatHistory.Message.builder()
                            .sender("ai")
                            .content(fullReply.toString())
                            .timestamp(Instant.now())
                            .build();
                    freshChat.getMessages().add(botMsg);
                    freshChat.setUpdatedAt(Instant.now());
                    chatHistoryRepository.save(freshChat);
                    logger.debug("Async chat completion saved for session {}", sessionId);
                });
    }

    public List<ChatSessionResponse> getChatSessions(String userId) {
        return chatHistoryRepository.findByUserIdOrderByUpdatedAtDesc(userId).stream()
                .map(this::mapToResponse)
                .collect(Collectors.toList());
    }

    public List<ChatSessionResponse> searchChatSessions(String userId, String query) {
        return chatHistoryRepository.findByUserIdAndSessionTitleContainingIgnoreCaseOrderByUpdatedAtDesc(userId, query).stream()
                .map(this::mapToResponse)
                .collect(Collectors.toList());
    }

    public ChatHistory getChatSessionDetails(String sessionId, String userId) {
        ChatHistory chat = chatHistoryRepository.findById(sessionId)
                .orElseThrow(() -> new ResourceNotFoundException("Chat session not found"));
        
        if (!chat.getUserId().equals(userId)) {
            throw new BadRequestException("Unauthorized access to chat session.");
        }
        
        return chat;
    }

    public ChatHistory createChatSession(String userId) {
        logger.info("Creating new chatbot conversation session for user: {}", userId);
        ChatHistory chat = ChatHistory.builder()
                .userId(userId)
                .sessionTitle("New Conversation")
                .createdAt(Instant.now())
                .updatedAt(Instant.now())
                .build();
        return chatHistoryRepository.save(chat);
    }

    public ChatHistory.Message sendMessage(String sessionId, String userId, MessageRequest request) {
        ChatHistory chat = getChatSessionDetails(sessionId, userId);
        
        // Append user message
        ChatHistory.Message userMessage = ChatHistory.Message.builder()
                .sender("user")
                .content(request.getContent())
                .timestamp(Instant.now())
                .build();
        chat.getMessages().add(userMessage);

        // Auto-summarize first message to set a clean session title
        if ("New Conversation".equals(chat.getSessionTitle())) {
            String title = generateTitleFromMessage(request.getContent());
            chat.setSessionTitle(title);
        }

        // Invoke AI Service with history
        logger.debug("Invoking Gemini chat completion for session: {}", sessionId);
        String reply = aiService.generateChatReply(CHATBOT_SYSTEM_PROMPT, chat.getMessages());

        // Append bot message
        ChatHistory.Message botMessage = ChatHistory.Message.builder()
                .sender("ai")
                .content(reply)
                .timestamp(Instant.now())
                .build();
        chat.getMessages().add(botMessage);
        chat.setUpdatedAt(Instant.now());

        chatHistoryRepository.save(chat);

        // Update learning progress & study timer
        progressService.incrementChats(userId);

        return botMessage;
    }

    public void deleteChatSession(String sessionId, String userId) {
        ChatHistory chat = getChatSessionDetails(sessionId, userId);
        chatHistoryRepository.delete(chat);
        logger.info("Chat session {} deleted successfully", sessionId);
    }

    private ChatSessionResponse mapToResponse(ChatHistory chat) {
        return ChatSessionResponse.builder()
                .id(chat.getId())
                .sessionTitle(chat.getSessionTitle())
                .messageCount(chat.getMessages().size())
                .createdAt(chat.getCreatedAt())
                .updatedAt(chat.getUpdatedAt())
                .build();
    }

    private String generateTitleFromMessage(String content) {
        if (content == null || content.isBlank()) return "Practice session";
        String[] words = content.trim().split("\\s+");
        if (words.length <= 4) {
            return content.trim();
        }
        return words[0] + " " + words[1] + " " + words[2] + " " + words[3] + "...";
    }
}
