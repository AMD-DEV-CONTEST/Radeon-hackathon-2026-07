package com.indusmind.config;

import com.indusmind.domain.UserAccount;
import com.indusmind.repository.UserRepository;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
public class DemoDataConfig {
    @Bean
    CommandLineRunner seedUsers(UserRepository users, PasswordEncoder encoder) {
        return args -> {
            create(users, encoder, "admin", "Admin@123", "Demo Administrator", "ADMIN");
            create(users, encoder, "engineer", "Engineer@123", "Maintenance Engineer", "ENGINEER");
        };
    }

    private void create(UserRepository users, PasswordEncoder encoder, String username, String password,
                        String displayName, String role) {
        if (users.findByUsername(username).isEmpty()) {
            UserAccount user = new UserAccount();
            user.setUsername(username);
            user.setPasswordHash(encoder.encode(password));
            user.setDisplayName(displayName);
            user.setRole(role);
            users.save(user);
        }
    }
}

