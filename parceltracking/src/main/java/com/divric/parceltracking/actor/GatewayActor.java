package com.divric.parceltracking.actor;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import com.divric.parceltracking.service.SessionService;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.actor.Props;

/**
 * Top-level Pekko actor — entry point for all messages from AgentTools.
 * Routes messages to SupervisorActor and handles WorkerResult/WorkerFailed/Shutdown.
 * Logger: traces message routing for debugging the actor flow.
 */
public class GatewayActor extends AbstractActor {

    private final ActorRef supervisor;

    public GatewayActor(SessionService sessionService) {
        this.supervisor = getContext().actorOf(SupervisorActor.props(sessionService), "supervisor");
    }

    public static Props props(SessionService sessionService) {
        return Props.create(GatewayActor.class, () -> new GatewayActor(sessionService));
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.TrackParcel.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.GetParcelStatus.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.QueryRag.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.IngestDocument.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.ChatMessage.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.SessionEvent.class, msg -> supervisor.forward(msg, getContext()))
            .match(ActorMessage.WorkerResult.class, this::onWorkerResult)
            .match(ActorMessage.WorkerFailed.class, this::onWorkerFailed)
            .match(ActorMessage.Shutdown.class, msg -> onShutdown())
            .build();
    }

    private void onWorkerResult(ActorMessage.WorkerResult msg) {
        getSender().tell(msg, getSelf());
    }

    private void onWorkerFailed(ActorMessage.WorkerFailed msg) {
        getSender().tell(msg, getSelf());
    }

    private void onShutdown() {
        getContext().getSystem().terminate();
    }
}