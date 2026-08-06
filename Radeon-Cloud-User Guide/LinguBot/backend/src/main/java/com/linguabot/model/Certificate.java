package com.linguabot.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;

@Document(collection = "certificates")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Certificate {
    @Id
    private String id; // This will act as the certificate verification ID

    @Indexed
    private String userId;

    private String recipientName;
    private String courseName;
    private Instant issueDate;
    private int quizzesCompleted;
    private int lessonsCompleted;
    private double averageQuizAccuracy;
    private String verificationCode;
}
