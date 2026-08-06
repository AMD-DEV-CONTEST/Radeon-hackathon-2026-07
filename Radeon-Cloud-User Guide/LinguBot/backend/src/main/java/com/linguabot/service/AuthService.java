package com.linguabot.service;

import com.linguabot.dto.*;
import com.linguabot.exception.BadRequestException;
import com.linguabot.exception.ResourceNotFoundException;
import com.linguabot.model.Role;
import com.linguabot.model.User;
import com.linguabot.repository.UserRepository;
import com.linguabot.security.JwtTokenProvider;
import com.linguabot.security.UserPrincipal;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
public class AuthService {

    private static final Logger logger = LoggerFactory.getLogger(AuthService.class);

    @Autowired
    private AuthenticationManager authenticationManager;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtTokenProvider tokenProvider;

    public AuthResponse login(LoginRequest loginRequest) {
        logger.debug("Attempting authentication for email: {}", loginRequest.getEmail());
        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(
                        loginRequest.getEmail(),
                        loginRequest.getPassword()
                )
        );

        SecurityContextHolder.getContext().setAuthentication(authentication);
        String jwt = tokenProvider.generateToken(authentication);

        UserPrincipal userPrincipal = (UserPrincipal) authentication.getPrincipal();
        List<String> roles = userPrincipal.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .collect(Collectors.toList());

        return AuthResponse.builder()
                .token(jwt)
                .id(userPrincipal.getId())
                .username(userPrincipal.getActualUsername())
                .email(userPrincipal.getEmail())
                .roles(roles)
                .build();
    }

    public MessageResponse register(RegisterRequest registerRequest) {
        if (userRepository.existsByEmail(registerRequest.getEmail())) {
            throw new BadRequestException("Email address already in use.");
        }

        if (userRepository.existsByUsername(registerRequest.getUsername())) {
            throw new BadRequestException("Username already in use.");
        }

        // Set roles: Admin for admin email/username, User for others
        Set<Role> roles = new HashSet<>();
        roles.add(Role.ROLE_USER);
        if (registerRequest.getEmail().equalsIgnoreCase("admin@linguabot.com") 
                || registerRequest.getUsername().toLowerCase().contains("admin")) {
            roles.add(Role.ROLE_ADMIN);
            logger.info("Registering admin user: {}", registerRequest.getEmail());
        }

        User user = User.builder()
                .username(registerRequest.getUsername())
                .email(registerRequest.getEmail())
                .password(passwordEncoder.encode(registerRequest.getPassword()))
                .roles(roles)
                .build();

        userRepository.save(user);
        logger.info("User registered successfully: {}", user.getEmail());

        return new MessageResponse("User registered successfully", true);
    }

    public MessageResponse forgotPassword(ForgotPasswordRequest request) {
        logger.debug("Received forgot password request for email: {}", request.getEmail());
        // For security reasons, do not reveal if user does not exist. Just return success.
        User user = userRepository.findByEmail(request.getEmail()).orElse(null);
        if (user != null) {
            String token = UUID.randomUUID().toString();
            user.setResetToken(token);
            user.setResetTokenExpiry(Instant.now().plus(15, ChronoUnit.MINUTES));
            userRepository.save(user);

            // Log the reset link in the console as mail sending mock
            logger.info("=========================================");
            logger.info("PASSWORD RESET LINK (SIMULATED):");
            logger.info("http://localhost:3000/reset-password?token={}", token);
            logger.info("=========================================");
        }

        return new MessageResponse("If that email address is in our system, we have sent a reset link to it.", true);
    }

    public MessageResponse resetPassword(ResetPasswordRequest request) {
        User user = userRepository.findByResetToken(request.getToken())
                .orElseThrow(() -> new BadRequestException("Invalid reset token."));

        if (user.getResetTokenExpiry().isBefore(Instant.now())) {
            throw new BadRequestException("Reset token has expired.");
        }

        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
        user.setResetToken(null);
        user.setResetTokenExpiry(null);
        userRepository.save(user);

        logger.info("Password reset successfully for user: {}", user.getEmail());
        return new MessageResponse("Password has been reset successfully.", true);
    }

    public ProfileResponse getProfile(String email) {
        User user = userRepository.findByEmail(email)
                .orElseThrow(() -> new ResourceNotFoundException("User not found"));

        List<String> roles = user.getRoles().stream()
                .map(Role::name)
                .collect(Collectors.toList());

        return ProfileResponse.builder()
                .id(user.getId())
                .username(user.getUsername())
                .email(user.getEmail())
                .roles(roles)
                .createdAt(user.getCreatedAt())
                .build();
    }
}
