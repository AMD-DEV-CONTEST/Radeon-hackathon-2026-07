package com.linguabot.controller;

import com.linguabot.dto.DashboardResponse;
import com.linguabot.dto.ProgressDetailsResponse;
import com.linguabot.model.Certificate;
import com.linguabot.model.Progress;
import com.linguabot.repository.CertificateRepository;
import com.linguabot.security.UserPrincipal;
import com.linguabot.service.CertificateGenerator;
import com.linguabot.service.ProgressService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/progress")
public class ProgressController {

    @Autowired
    private ProgressService progressService;

    @Autowired
    private CertificateGenerator certificateGenerator;

    @Autowired
    private CertificateRepository certificateRepository;

    @GetMapping("/dashboard")
    public ResponseEntity<DashboardResponse> getDashboardData(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        DashboardResponse response = progressService.getDashboardData(userPrincipal.getId(), userPrincipal.getActualUsername());
        return ResponseEntity.ok(response);
    }

    @GetMapping
    public ResponseEntity<ProgressDetailsResponse> getProgressDetails(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        ProgressDetailsResponse response = progressService.getProgressDetails(userPrincipal.getId());
        return ResponseEntity.ok(response);
    }

    @GetMapping("/streak")
    public ResponseEntity<Map<String, Object>> getUserStreak(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }
        Progress progress = progressService.getOrCreateProgress(userPrincipal.getId());
        progressService.updateStreak(progress);

        Map<String, Object> response = new HashMap<>();
        response.put("streak", progress.getStreak());
        response.put("lastActivityDate", progress.getLastActivityDate());
        return ResponseEntity.ok(response);
    }

    @GetMapping("/certificate")
    public ResponseEntity<Map<String, Object>> getCertificateData(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }

        ProgressDetailsResponse progressDetails = progressService.getProgressDetails(userPrincipal.getId());
        if (!progressDetails.isCertificateEligible()) {
            return ResponseEntity.badRequest().body(Map.of("message", "You are not eligible for a certificate yet. Please complete more hours and quizzes!"));
        }

        String verificationCode = "LB-" + userPrincipal.getId().substring(0, 5).toUpperCase() + "-" + (userPrincipal.getId().hashCode() & 0xffff);
        Certificate certificate = certificateRepository.findByUserIdAndCourseName(userPrincipal.getId(), "LinguaBot AI Language Immersion Course")
                .orElseGet(() -> {
                    Certificate newCert = Certificate.builder()
                            .userId(userPrincipal.getId())
                            .recipientName(userPrincipal.getActualUsername())
                            .courseName("LinguaBot AI Language Immersion Course")
                            .issueDate(Instant.now())
                            .quizzesCompleted(progressDetails.getProgress().getCompletedQuizzesCount())
                            .lessonsCompleted(progressDetails.getProgress().getTotalChats())
                            .averageQuizAccuracy(progressDetails.getProgress().getAverageQuizAccuracy())
                            .verificationCode(verificationCode)
                            .build();
                    return certificateRepository.save(newCert);
                });

        Map<String, Object> response = new HashMap<>();
        response.put("recipientName", certificate.getRecipientName());
        response.put("courseName", certificate.getCourseName());
        response.put("issueDate", certificate.getIssueDate().toString());
        response.put("verificationCode", certificate.getVerificationCode());
        response.put("status", "VALID");

        return ResponseEntity.ok(response);
    }

    @GetMapping("/certificate/pdf")
    public ResponseEntity<byte[]> downloadCertificatePdf(@AuthenticationPrincipal UserPrincipal userPrincipal) {
        if (userPrincipal == null) {
            return ResponseEntity.status(401).build();
        }

        ProgressDetailsResponse progressDetails = progressService.getProgressDetails(userPrincipal.getId());
        if (!progressDetails.isCertificateEligible()) {
            return ResponseEntity.badRequest().body("You are not eligible for a certificate yet.".getBytes());
        }

        try {
            String verificationCode = "LB-" + userPrincipal.getId().substring(0, 5).toUpperCase() + "-" + (userPrincipal.getId().hashCode() & 0xffff);
            Certificate certificate = certificateRepository.findByUserIdAndCourseName(userPrincipal.getId(), "LinguaBot AI Language Immersion Course")
                    .orElseGet(() -> {
                        Certificate newCert = Certificate.builder()
                                .userId(userPrincipal.getId())
                                .recipientName(userPrincipal.getActualUsername())
                                .courseName("LinguaBot AI Language Immersion Course")
                                .issueDate(Instant.now())
                                .quizzesCompleted(progressDetails.getProgress().getCompletedQuizzesCount())
                                .lessonsCompleted(progressDetails.getProgress().getTotalChats())
                                .averageQuizAccuracy(progressDetails.getProgress().getAverageQuizAccuracy())
                                .verificationCode(verificationCode)
                                .build();
                        return certificateRepository.save(newCert);
                    });

            byte[] pdfBytes = certificateGenerator.generateCertificatePdf(
                    certificate.getRecipientName(),
                    certificate.getVerificationCode(),
                    certificate.getIssueDate()
            );

            org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_PDF);
            headers.setContentDispositionFormData("filename", "linguabot_certificate.pdf");
            headers.setContentLength(pdfBytes.length);

            return new ResponseEntity<>(pdfBytes, headers, org.springframework.http.HttpStatus.OK);
        } catch (Exception e) {
            return ResponseEntity.status(500).body(("Failed to generate PDF certificate: " + e.getMessage()).getBytes());
        }
    }
}
