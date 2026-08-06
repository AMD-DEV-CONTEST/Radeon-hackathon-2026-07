package com.library.assistant.service;

import com.library.assistant.dto.ChatResponseDTO;

public interface GeminiService {
    ChatResponseDTO generateResponse(String question);
}
