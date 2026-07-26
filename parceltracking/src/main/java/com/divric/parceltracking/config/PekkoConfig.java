package com.divric.parceltracking.config;

import com.divric.parceltracking.actor.GatewayActor;
import com.divric.parceltracking.service.SessionService;
import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.actor.ActorSystem;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;

import java.util.Arrays;

@Configuration
public class PekkoConfig {

    @Bean
    public ActorSystem actorSystem(Environment environment) {
        // Start with the base application.conf
        Config baseConfig = ConfigFactory.load("application.conf");

        // If the "prod" profile is active, overlay application-prod.conf
        boolean isProd = Arrays.asList(environment.getActiveProfiles()).contains("prod");
        if (isProd) {
            Config prodConfig = ConfigFactory.load("application-prod.conf");
            baseConfig = prodConfig.withFallback(baseConfig).resolve();
        }

        return ActorSystem.create("parceltracking-system", baseConfig);
    }

    @Bean
    public ActorRef gatewayActor(ActorSystem system, SessionService sessionService) {
        return system.actorOf(GatewayActor.props(sessionService), "gateway");
    }
}
