package com.linguabot.controller;

import com.linguabot.dto.AdminStatsResponse;
import com.linguabot.dto.AdminUserResponse;
import com.linguabot.dto.FeedbackRequest;
import com.linguabot.model.Feedback;
import com.linguabot.model.Quiz;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.AdminService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/admin")
public class AdminController {

    @Autowired
    private AdminService adminService;

    @GetMapping("/users")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<List<AdminUserResponse>> getUsersList(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(adminService.getUsersList());
    }

    @DeleteMapping("/users/{userId}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> deleteUser(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String userId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        // Avoid self-deletion
        if (userPrincipal.getId().equals(userId)) {
            return ResponseEntity.badRequest().build();
        }
        adminService.deleteUser(userId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/quizzes")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<List<Quiz>> getQuizzes(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(adminService.getQuizzes());
    }

    @DeleteMapping("/quizzes/{quizId}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> deleteQuiz(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String quizId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        adminService.deleteQuiz(quizId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/feedback")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<List<Feedback>> getFeedbackList(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(adminService.getFeedback());
    }

    @DeleteMapping("/feedback/{feedbackId}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> deleteFeedback(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String feedbackId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        adminService.deleteFeedback(feedbackId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/stats")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<AdminStatsResponse> getPlatformStats(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(adminService.getPlatformStats());
    }

    // Accessible to USER or ADMIN for reviews submission
    @PostMapping("/feedback")
    public ResponseEntity<Feedback> submitFeedback(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @Valid @RequestBody FeedbackRequest feedbackRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        Feedback feedback = adminService.submitFeedback(
                userPrincipal.getId(),
                userPrincipal.getActualUsername(),
                feedbackRequest
        );
        return ResponseEntity.ok(feedback);
    }
}
