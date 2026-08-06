package com.linguabot.dto;

import com.linguabot.model.GrammarHistory;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GrammarResponse {
    private String originalText;
    private String correctedText;
    private List<GrammarHistory.ExplanationItem> explanations;
    private String tone;
}
