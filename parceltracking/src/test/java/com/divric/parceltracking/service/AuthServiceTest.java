package com.divric.parceltracking.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock
    private SessionService sessionService;

    @InjectMocks
    private AuthService authService;

    @Test
    void createSession_shouldGenerateUUIDAndSave() {
        String sessionId = authService.createSession();

        assertThat(sessionId).isNotNull();
        assertThat(UUID.fromString(sessionId)).isNotNull(); // valid UUID
        verify(sessionService, times(1)).saveSession(any(UUID.class), eq("chat-session"));
    }

    @Test
    void validateSession_withValidSession_shouldReturnTrue() {
        UUID sessionId = UUID.randomUUID();
        when(sessionService.findSession(sessionId)).thenReturn(Optional.of(sessionId));

        boolean result = authService.validateSession(sessionId.toString());

        assertThat(result).isTrue();
        verify(sessionService, times(1)).findSession(sessionId);
    }

    @Test
    void validateSession_withInvalidSession_shouldReturnFalse() {
        UUID sessionId = UUID.randomUUID();
        when(sessionService.findSession(sessionId)).thenReturn(Optional.empty());

        boolean result = authService.validateSession(sessionId.toString());

        assertThat(result).isFalse();
        verify(sessionService, times(1)).findSession(sessionId);
    }

    @Test
    void validateSession_withInvalidUUID_shouldReturnFalse() {
        boolean result = authService.validateSession("not-a-uuid");

        assertThat(result).isFalse();
        verify(sessionService, never()).findSession(any());
    }

    @Test
    void validateSession_withNullSession_shouldReturnFalse() {
        boolean result = authService.validateSession(null);

        assertThat(result).isFalse();
        verify(sessionService, never()).findSession(any());
    }

    @Test
    void validateSession_withEmptyString_shouldReturnFalse() {
        boolean result = authService.validateSession("");

        assertThat(result).isFalse();
        verify(sessionService, never()).findSession(any());
    }
}