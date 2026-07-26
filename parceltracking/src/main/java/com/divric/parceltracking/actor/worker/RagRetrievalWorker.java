package com.divric.parceltracking.actor.worker;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.Props;

public class RagRetrievalWorker extends AbstractActor {

    public static Props props() {
        return Props.create(RagRetrievalWorker.class, RagRetrievalWorker::new);
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.QueryRag.class, this::onQueryRag)
            .build();
    }

    private void onQueryRag(ActorMessage.QueryRag msg) {
        String result = "RAG result for query: \"" + msg.query() + "\" (session: " + msg.sessionId() + ")";
        getSender().tell(new ActorMessage.WorkerResult(msg.sessionId(), result), getSelf());
    }
}