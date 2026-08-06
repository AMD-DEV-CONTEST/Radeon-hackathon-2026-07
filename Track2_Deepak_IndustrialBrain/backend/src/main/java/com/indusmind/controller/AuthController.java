package com.indusmind.controller;

import com.indusmind.repository.UserRepository;
import com.indusmind.security.JwtService;
import com.indusmind.service.AuditService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final UserRepository users;
    private final PasswordEncoder encoder;
    private final JwtService jwt;
    private final AuditService audit;
    public AuthController(UserRepository users, PasswordEncoder encoder, JwtService jwt, AuditService audit) {
        this.users = users; this.encoder = encoder; this.jwt = jwt; this.audit = audit;
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest request) {
        return users.findByUsername(request.username())
                .filter(user -> encoder.matches(request.password(), user.getPasswordHash()))
                .<ResponseEntity<?>>map(user -> {
                    audit.record("LOGIN_SUCCESS", "user", user.getUsername(), null);
                    return ResponseEntity.ok(Map.of(
                            "token", jwt.create(user.getUsername(), user.getRole()),
                            "username", user.getUsername(),
                            "displayName", user.getDisplayName(),
                            "role", user.getRole()));
                })
                .orElseGet(() -> {
                    audit.record("LOGIN_FAILED", "user", request.username(), null);
                    return ResponseEntity.status(401).body(Map.of("message", "Invalid username or password"));
                });
    }
    public record LoginRequest(@NotBlank String username, @NotBlank String password) {}
}

