package com.linguabot.controller;

import com.linguabot.dto.TranslationRequest;
import com.linguabot.dto.TranslationResponse;
import com.linguabot.model.TranslationHistory;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.TranslationService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/translation")
public class TranslationController {

    @Autowired
    private TranslationService translationService;

    @PostMapping("/translate")
    public ResponseEntity<TranslationResponse> translateText(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @Valid @RequestBody TranslationRequest translationRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        TranslationResponse response = translationService.translate(userPrincipal.getId(), translationRequest);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/history")
    public ResponseEntity<List<TranslationHistory>> getHistory(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        List<TranslationHistory> history = translationService.getHistory(userPrincipal.getId());
        return ResponseEntity.ok(history);
    }

    @GetMapping("/favorites")
    public ResponseEntity<List<TranslationHistory>> getFavorites(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        List<TranslationHistory> favorites = translationService.getFavorites(userPrincipal.getId());
        return ResponseEntity.ok(favorites);
    }

    @PutMapping("/history/{id}/favorite")
    public ResponseEntity<TranslationResponse> toggleFavorite(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String id) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        TranslationResponse response = translationService.toggleFavorite(id, userPrincipal.getId());
        return ResponseEntity.ok(response);
    }

    @DeleteMapping("/history/{id}")
    public ResponseEntity<Void> deleteHistoryItem(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @PathVariable String id) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        translationService.deleteTranslation(id, userPrincipal.getId());
        return ResponseEntity.noContent().build();
    }
}
