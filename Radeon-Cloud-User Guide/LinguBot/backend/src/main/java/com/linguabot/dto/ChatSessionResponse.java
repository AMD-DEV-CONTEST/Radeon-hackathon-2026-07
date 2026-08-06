package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ChatSessionResponse {
    private String id;
    private String sessionTitle;
    private int messageCount;
    private Instant createdAt;
    private Instant updatedAt;
}
