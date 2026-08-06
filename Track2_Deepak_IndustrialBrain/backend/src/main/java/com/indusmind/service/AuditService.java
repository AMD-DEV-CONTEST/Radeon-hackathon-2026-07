package com.indusmind.service;

import com.indusmind.domain.AuditLog;
import com.indusmind.repository.AuditLogRepository;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

@Service
public class AuditService {
    private final AuditLogRepository logs;

    public AuditService(AuditLogRepository logs) {
        this.logs = logs;
    }

    public void record(String action, String targetType, String targetId, String detail) {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        String actor = auth != null ? auth.getName() : "system";
        record(actor, action, targetType, targetId, detail);
    }

    // Use this overload from background/async threads: Spring Security's
    // SecurityContextHolder is thread-local and is NOT propagated to
    // @Async worker threads (they're pooled and reused across requests), so
    // the actor must be captured on the original request thread and passed
    // in explicitly instead of read back out of the (empty) context here.
    public void record(String actor, String action, String targetType, String targetId, String detail) {
        logs.save(new AuditLog(actor, action, targetType, targetId, detail));
    }
}
