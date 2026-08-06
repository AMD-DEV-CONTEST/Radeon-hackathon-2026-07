package com.library.assistant.controller;

import com.library.assistant.dto.ChatRequestDTO;
import com.library.assistant.dto.ChatResponseDTO;
import com.library.assistant.service.GeminiService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/ai")
@CrossOrigin(origins = "*")
public class AIController {

    private final GeminiService geminiService;

    @Autowired
    public AIController(GeminiService geminiService) {
        this.geminiService = geminiService;
    }

    @PostMapping("/chat")
    public ResponseEntity<ChatResponseDTO> chat(@Valid @RequestBody ChatRequestDTO request) {
        ChatResponseDTO response = geminiService.generateResponse(request.getQuestion());
        return ResponseEntity.ok(response);
    }
}
