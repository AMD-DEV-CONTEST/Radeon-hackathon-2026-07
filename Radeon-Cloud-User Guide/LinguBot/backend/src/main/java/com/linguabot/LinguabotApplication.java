package com.linguabot;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.data.mongodb.config.EnableMongoAuditing;

@SpringBootApplication
@EnableMongoAuditing
public class LinguabotApplication {
    public static void main(String[] args) {
        SpringApplication.run(LinguabotApplication.class, args);
    }
}
