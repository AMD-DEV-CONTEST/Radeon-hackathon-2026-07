package com.divric.parceltracking.actor;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import com.divric.parceltracking.actor.worker.ParcelTrackingWorker;
import com.divric.parceltracking.actor.worker.RagRetrievalWorker;
import com.divric.parceltracking.service.SessionService;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.ActorRef;
import org.apache.pekko.actor.Props;

/**
 * Pekko actor that manages child workers — ParcelTrackingWorker, RagRetrievalWorker,
 * IngestionActor, and UserSessionActor. Forwards incoming messages to the correct child
 * and relays WorkerResult/WorkerFailed responses back up to GatewayActor.
 * Logger: traces message dispatch to child actors for monitoring the actor hierarchy.
 */
public class SupervisorActor extends AbstractActor {
    // Injected child actor references for message routing
    private final ActorRef parcelTrackingWorker;
    private final ActorRef ragRetrievalWorker;
    private final ActorRef ingestionActor;
    private final ActorRef userSessionActor;

    public SupervisorActor(SessionService sessionService) {
        this.parcelTrackingWorker = getContext().actorOf(ParcelTrackingWorker.props(), "parcelTrackingWorker");
        this.ragRetrievalWorker = getContext().actorOf(RagRetrievalWorker.props(), "ragRetrievalWorker");
        this.ingestionActor = getContext().actorOf(IngestionActor.props(), "ingestionActor");
        this.userSessionActor = getContext().actorOf(UserSessionActor.props(sessionService), "userSessionActor");
    }

    public static Props props(SessionService sessionService) {
        return Props.create(SupervisorActor.class, () -> new SupervisorActor(sessionService));
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.TrackParcel.class, msg -> parcelTrackingWorker.forward(msg, getContext()))
            .match(ActorMessage.GetParcelStatus.class, msg -> parcelTrackingWorker.forward(msg, getContext()))
            .match(ActorMessage.QueryRag.class, msg -> ragRetrievalWorker.forward(msg, getContext()))
            .match(ActorMessage.IngestDocument.class, msg -> ingestionActor.forward(msg, getContext()))
            .match(ActorMessage.ChatMessage.class, msg -> userSessionActor.forward(msg, getContext()))
            .match(ActorMessage.SessionEvent.class, msg -> userSessionActor.forward(msg, getContext()))
            .match(ActorMessage.WorkerResult.class, this::onWorkerResult)
            .match(ActorMessage.WorkerFailed.class, this::onWorkerFailed)
            .build();
    }

    private void onWorkerResult(ActorMessage.WorkerResult msg) {
        getSender().tell(msg, getSelf());
    }

    private void onWorkerFailed(ActorMessage.WorkerFailed msg) {
        getSender().tell(msg, getSelf());
    }
}