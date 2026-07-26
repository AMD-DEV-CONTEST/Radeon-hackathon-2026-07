package com.divric.parceltracking.controller;

import com.divric.parceltracking.dto.ChatRequest;
import com.divric.parceltracking.dto.ChatResponse;
import com.divric.parceltracking.engine.SupervisorActorEngine;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for user chat interactions with the AI assistant.
 * Accepts user messages with session context, delegates to SupervisorActorEngine for
 * actor-based processing, and returns replies.
 */
@RestController
@RequestMapping("/api/chat")
@Tag(name = "Chat", description = "Chat with the parcel tracking AI assistant — ask about tracking, policies, and more")
public class ChatController {

    private final SupervisorActorEngine engine;

    public ChatController(SupervisorActorEngine engine) {
        this.engine = engine;
    }

    @PostMapping
    @Operation(
        summary = "Send a chat message",
        description = "Process a user message through the AI assistant. Requires a valid session ID obtained from POST /api/auth/session."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Message processed successfully — AI reply returned",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = ChatResponse.class),
                examples = @ExampleObject(value = "{\"reply\":\"Your package TRK-00001 is currently in transit from New York, NY to Los Angeles, CA. Estimated delivery is August 5, 2026.\",\"sessionId\":\"a1b2c3d4-e5f6-7890-abcd-ef1234567890\"}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Invalid request — missing or empty message/sessionId",
            content = @Content
        ),
        @ApiResponse(
            responseCode = "401",
            description = "Unauthorized — invalid or expired session ID",
            content = @Content
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — AI processing failed",
            content = @Content
        )
    })
    public ChatResponse chat(@RequestBody ChatRequest request) {
        String reply = engine.sendChatMessage(request.getMessage(), request.getSessionId());
        return new ChatResponse(reply, request.getSessionId());
    }
}