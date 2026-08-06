package com.indusmind.security;

import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Date;

@Service
public class JwtService {
    private static final long EXPIRY_SECONDS = 8 * 3600;
    private final SecretKey key;

    public JwtService(@Value("${indusmind.jwt-secret}") String secret) {
        this.key = Keys.hmacShaKeyFor(deriveKeyBytes(secret));
    }

    // HS256 requires a key of at least 256 bits (32 bytes). A short/simple
    // secret in an env var would otherwise throw a WeakKeyException at
    // startup, so any secret shorter than that is stretched via SHA-256
    // first. Secrets that are already >= 32 bytes are used as-is.
    private static byte[] deriveKeyBytes(String secret) {
        byte[] raw = secret.getBytes(StandardCharsets.UTF_8);
        if (raw.length >= 32) {
            return raw;
        }
        try {
            return MessageDigest.getInstance("SHA-256").digest(raw);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("Unable to derive JWT signing key", ex);
        }
    }

    public String create(String username, String role) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(username)
                .claim("role", role)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plusSeconds(EXPIRY_SECONDS)))
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    public Claims verify(String token) {
        try {
            io.jsonwebtoken.Claims payload = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            String role = payload.get("role", String.class);
            if (role == null || role.isBlank()) {
                throw new IllegalArgumentException("Token is missing the role claim");
            }
            return new Claims(payload.getSubject(), role);
        } catch (JwtException | IllegalArgumentException ex) {
            throw new IllegalArgumentException("Invalid token", ex);
        }
    }

    public record Claims(String username, String role) {}
}
