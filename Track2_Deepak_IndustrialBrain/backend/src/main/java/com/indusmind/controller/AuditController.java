package com.indusmind.controller;

import com.indusmind.domain.AuditLog;
import com.indusmind.repository.AuditLogRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;

@RestController
@RequestMapping("/api/audit")
public class AuditController {
    private final AuditLogRepository logs;
    public AuditController(AuditLogRepository logs) { this.logs = logs; }

    @GetMapping
    public List<AuditLog> recent() {
        return logs.findTop200ByOrderByCreatedAtDesc();
    }
}
