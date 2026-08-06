package com.linguabot.controller;

import com.linguabot.dto.ChatSessionResponse;
import com.linguabot.dto.MessageRequest;
import com.linguabot.exception.BadRequestException;
import com.linguabot.model.ChatHistory;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.ChatService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/chats")
public class ChatController {

    @Autowired
    private ChatService chatService;

    @GetMapping
    public ResponseEntity<List<ChatSessionResponse>> getChatSessions(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @RequestParam(value = "q", required = false) String query) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        
        List<ChatSessionResponse> sessions;
        if (query != null && !query.isBlank()) {
            sessions = chatService.searchChatSessions(userPrincipal.getId(), query);
        } else {
            sessions = chatService.getChatSessions(userPrincipal.getId());
        }
        return ResponseEntity.ok(sessions);
    }

    @PostMapping
    public ResponseEntity<ChatHistory> createChatSession(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        ChatHistory session = chatService.createChatSession(userPrincipal.getId());
        return ResponseEntity.ok(session);
    }

    @GetMapping("/{sessionId}")
    public ResponseEntity<ChatHistory> getChatSession(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String sessionId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        ChatHistory chat = chatService.getChatSessionDetails(sessionId, userPrincipal.getId());
        return ResponseEntity.ok(chat);
    }

    @PutMapping("/{sessionId}/title")
    public ResponseEntity<ChatHistory> renameChatSession(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String sessionId,
            @RequestBody Map<String, String> body) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        String newTitle = body.get("title");
        if (newTitle == null || newTitle.isBlank()) {
            return ResponseEntity.badRequest().build();
        }
        ChatHistory session = chatService.renameChatSession(sessionId, userPrincipal.getId(), newTitle);
        return ResponseEntity.ok(session);
    }

    @PostMapping("/{sessionId}/messages")
    public ResponseEntity<ChatHistory.Message> sendMessage(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String sessionId,
            @Valid @RequestBody MessageRequest messageRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        ChatHistory.Message aiResponse = chatService.sendMessage(sessionId, userPrincipal.getId(), messageRequest);
        return ResponseEntity.ok(aiResponse);
    }

    @PostMapping(value = "/{sessionId}/messages/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter sendMessageStream(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String sessionId,
            @Valid @RequestBody MessageRequest messageRequest) {
        if (userPrincipal == null) {
            throw new BadRequestException("Unauthorized access to chat stream.");
        }

        SseEmitter emitter = new SseEmitter(180000L); // 3-minute timeout

        chatService.sendMessageStream(sessionId, userPrincipal.getId(), messageRequest)
                .subscribe(
                        chunk -> {
                            try {
                                emitter.send(SseEmitter.event().data(chunk));
                            } catch (IOException e) {
                                // Client disconnected
                            }
                        },
                        error -> {
                            try {
                                emitter.send(SseEmitter.event().name("error").data(error.getMessage()));
                            } catch (IOException e) {
                                // ignore
                            }
                            emitter.completeWithError(error);
                        },
                        () -> {
                            try {
                                emitter.send(SseEmitter.event().name("complete").data("[DONE]"));
                            } catch (IOException e) {
                                // ignore
                            }
                            emitter.complete();
                        }
                );

        return emitter;
    }

    @DeleteMapping("/{sessionId}")
    public ResponseEntity<Void> deleteChatSession(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String sessionId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        chatService.deleteChatSession(sessionId, userPrincipal.getId());
        return ResponseEntity.noContent().build();
    }
}
