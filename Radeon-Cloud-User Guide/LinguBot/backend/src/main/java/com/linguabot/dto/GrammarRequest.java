package com.linguabot.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class GrammarRequest {
    @NotBlank(message = "Text to check cannot be empty")
    private String text;

    @NotBlank(message = "Please select a correction tone")
    private String tone; // "Formal", "Professional", "Casual"
}
