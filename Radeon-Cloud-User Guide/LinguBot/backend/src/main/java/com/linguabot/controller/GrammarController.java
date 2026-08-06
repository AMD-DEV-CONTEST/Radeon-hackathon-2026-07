package com.linguabot.controller;

import com.linguabot.dto.GrammarRequest;
import com.linguabot.dto.GrammarResponse;
import com.linguabot.model.GrammarHistory;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.GrammarService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/grammar")
public class GrammarController {

    @Autowired
    private GrammarService grammarService;

    @PostMapping("/check")
    public ResponseEntity<GrammarResponse> checkGrammar(
            @AuthenticationPrincipal UserPrincipal userPrincipal,
            @Valid @RequestBody GrammarRequest grammarRequest) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        GrammarResponse response = grammarService.checkGrammar(userPrincipal.getId(), grammarRequest);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/history")
    public ResponseEntity<List<GrammarHistory>> getHistory(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        List<GrammarHistory> history = grammarService.getHistory(userPrincipal.getId());
        return ResponseEntity.ok(history);
    }
}
