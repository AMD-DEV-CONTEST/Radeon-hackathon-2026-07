package com.linguabot.controller;

import com.linguabot.dto.QuizGenerateRequest;
import com.linguabot.dto.QuizSubmitRequest;
import com.linguabot.dto.QuizSubmitResponse;
import com.linguabot.model.Quiz;
import com.linguabot.model.QuizAttempt;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.QuizService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/quizzes")
public class QuizController {

    @Autowired
    private QuizService quizService;

    @PostMapping("/generate")
    public ResponseEntity<Quiz> generateQuiz(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @Valid @RequestBody QuizGenerateRequest generateRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        Quiz quiz = quizService.generateQuiz(userPrincipal.getId(), generateRequest);
        return ResponseEntity.ok(quiz);
    }

    @GetMapping("/{quizId}")
    public ResponseEntity<Quiz> getQuizDetails(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String quizId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        Quiz quiz = quizService.getQuizDetails(quizId);
        // Note: For actual secure environments, we could mask correctAnswers on this route,
        // but for practice platforms, returning full details helps simple state management.
        return ResponseEntity.ok(quiz);
    }

    @PostMapping("/{quizId}/submit")
    public ResponseEntity<QuizSubmitResponse> submitQuiz(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String quizId,
            @Valid @RequestBody QuizSubmitRequest submitRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        QuizSubmitResponse response = quizService.submitQuiz(quizId, userPrincipal.getId(), submitRequest);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/attempts")
    public ResponseEntity<List<QuizAttempt>> getAttempts(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        List<QuizAttempt> attempts = quizService.getAttempts(userPrincipal.getId());
        return ResponseEntity.ok(attempts);
    }

    @GetMapping("/attempts/{attemptId}")
    public ResponseEntity<QuizAttempt> getAttemptDetails(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String attemptId) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        QuizAttempt attempt = quizService.getAttemptDetails(attemptId, userPrincipal.getId());
        return ResponseEntity.ok(attempt);
    }
}
