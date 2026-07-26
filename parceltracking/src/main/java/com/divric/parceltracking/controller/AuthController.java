package com.divric.parceltracking.controller;

import com.divric.parceltracking.service.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * REST controller for guest session authentication.
 * Creates new sessions (sets SESSION_ID httpOnly cookie) and validates existing ones.
 * Session auth is used for chat endpoints; admin endpoints use X-Admin-Key header instead.
 */
@RestController
@RequestMapping("/api/auth")
@Tag(name = "Authentication", description = "Guest session management — create and validate sessions for chat access")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/session")
    @Operation(
        summary = "Create a new guest session",
        description = "Generates a new session ID, sets it as an httpOnly cookie (SESSION_ID), and returns it in the response body. The session expires after 24 hours."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Session created successfully — sessionId returned in body and set as httpOnly cookie",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = Map.class),
                examples = @ExampleObject(value = "{\"sessionId\":\"a1b2c3d4-e5f6-7890-abcd-ef1234567890\"}"))
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — session creation failed",
            content = @Content
        )
    })
    public ResponseEntity<Map<String, String>> createSession(HttpServletResponse response) {
        String sessionId = authService.createSession();

        Cookie cookie = new Cookie("SESSION_ID", sessionId);
        cookie.setHttpOnly(true);
        cookie.setSecure(true);
        cookie.setPath("/");
        cookie.setMaxAge(86400); // 24 hours
        cookie.setAttribute("SameSite", "Lax");
        response.addCookie(cookie);

        return ResponseEntity.ok(Map.of("sessionId", sessionId));
    }

    @GetMapping("/session/validate")
    @Operation(
        summary = "Validate a session",
        description = "Check if a session ID (from the SESSION_ID cookie) is still valid and has not expired."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Validation result returned — true if session is valid, false otherwise",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = Map.class),
                examples = @ExampleObject(value = "{\"valid\":true}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Bad request — missing or malformed cookie",
            content = @Content
        )
    })
    public ResponseEntity<Map<String, Boolean>> validateSession(
            @CookieValue(value = "SESSION_ID", defaultValue = "") String sessionId) {
        boolean valid = authService.validateSession(sessionId);
        return ResponseEntity.ok(Map.of("valid", valid));
    }
}