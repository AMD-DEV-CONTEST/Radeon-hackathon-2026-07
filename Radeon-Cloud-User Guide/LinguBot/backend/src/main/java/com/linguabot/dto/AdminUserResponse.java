package com.linguabot.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AdminUserResponse {
    private String id;
    private String username;
    private String email;
    private List<String> roles;
    private int streak;
    private double totalHours;
    private int completedQuizzesCount;
    private Instant createdAt;
}
