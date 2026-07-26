package com.divric.parceltracking.actor;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import com.divric.parceltracking.service.SessionService;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.Props;

import java.util.UUID;

/**
 * Pekko actor that manages individual user chat sessions.
 * Handles ChatMessage and SessionEvent messages, updating session activity in Neon DB
 * via SessionService. Each instance represents one active user conversation.
 * Logger: traces session activity updates and event processing.
 */
public class UserSessionActor extends AbstractActor {

    private final SessionService sessionService;

    public UserSessionActor(SessionService sessionService) {
        this.sessionService = sessionService;
    }

    public static Props props(SessionService sessionService) {
        return Props.create(UserSessionActor.class, () -> new UserSessionActor(sessionService));
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.ChatMessage.class, this::onChatMessage)
            .match(ActorMessage.SessionEvent.class, this::onSessionEvent)
            .build();
    }

    private void onChatMessage(ActorMessage.ChatMessage msg) {
        // Update session activity in Neon DB
        try {
            UUID sessionId = UUID.fromString(msg.sessionId());
            sessionService.updateLastActivity(sessionId);
        } catch (IllegalArgumentException e) {
            // Invalid session ID format, ignore
        }

        String reply = "Session " + msg.sessionId() + " received: " + msg.message();
        getSender().tell(new ActorMessage.WorkerResult(msg.sessionId(), reply), getSelf());
    }

    private void onSessionEvent(ActorMessage.SessionEvent msg) {
        // Validate and update session on event
        try {
            UUID sessionId = UUID.fromString(msg.sessionId());
            if (sessionService.findSession(sessionId).isPresent()) {
                sessionService.updateLastActivity(sessionId);
                getSender().tell(
                    new ActorMessage.WorkerResult(msg.sessionId(), "Event processed: " + msg.event()),
                    getSelf()
                );
            } else {
                getSender().tell(
                    new ActorMessage.WorkerFailed(msg.sessionId(), "Session not found"),
                    getSelf()
                );
            }
        } catch (IllegalArgumentException e) {
            getSender().tell(
                new ActorMessage.WorkerFailed(msg.sessionId(), "Invalid session ID"),
                getSelf()
            );
        }
    }
}