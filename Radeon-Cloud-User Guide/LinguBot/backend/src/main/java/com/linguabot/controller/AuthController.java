package com.linguabot.controller;

import com.linguabot.dto.*;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/auth")
public class AuthController {

    @Autowired
    private AuthService authService;

    @PostMapping("/register")
    public ResponseEntity<MessageResponse> registerUser(@Valid @RequestBody RegisterRequest registerRequest) {
        MessageResponse response = authService.register(registerRequest);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/login")
    public ResponseEntity<AuthResponse> authenticateUser(@Valid @RequestBody LoginRequest loginRequest) {
        AuthResponse response = authService.login(loginRequest);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/forgot-password")
    public ResponseEntity<MessageResponse> forgotPassword(@Valid @RequestBody ForgotPasswordRequest request) {
        MessageResponse response = authService.forgotPassword(request);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/reset-password")
    public ResponseEntity<MessageResponse> resetPassword(@Valid @RequestBody ResetPasswordRequest request) {
        MessageResponse response = authService.resetPassword(request);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/profile")
    public ResponseEntity<ProfileResponse> getUserProfile(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        ProfileResponse response = authService.getProfile(userPrincipal.getEmail());
        return ResponseEntity.ok(response);
    }

    @PostMapping("/logout")
    public ResponseEntity<MessageResponse> logoutUser() {
        // Since JWT is stateless, the client simply discards the token.
        // We return a confirmation message.
        return ResponseEntity.ok(new MessageResponse("Logged out successfully.", true));
    }

    @Autowired
    private com.linguabot.repository.CertificateRepository certificateRepository;

    @GetMapping("/certificate/verify/{code}")
    public ResponseEntity<?> verifyCertificate(@PathVariable String code) {
        return certificateRepository.findByVerificationCode(code)
                .map(cert -> ResponseEntity.ok(java.util.Map.of(
                        "recipientName", cert.getRecipientName(),
                        "courseName", cert.getCourseName(),
                        "issueDate", cert.getIssueDate().toString(),
                        "verificationCode", cert.getVerificationCode(),
                        "status", "VALID"
                )))
                .orElseGet(() -> ResponseEntity.status(404).body(java.util.Map.of(
                        "message", "Certificate verification code not found."
                )));
    }
}
