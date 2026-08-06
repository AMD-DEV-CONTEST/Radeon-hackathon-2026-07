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
public class ActivityDto {
    private String type; // "CHAT", "GRAMMAR", "TRANSLATION", "QUIZ"
    private String title;
    private String description;
    private Instant timestamp;
}
