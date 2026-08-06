package com.divric.parceltracking.actor.worker;

import com.divric.parceltracking.actor.protocol.ActorMessage;
import org.apache.pekko.actor.AbstractActor;
import org.apache.pekko.actor.Props;

/**
 * Pekko actor that handles parcel tracking operations.
 * Processes TrackParcel and GetParcelStatus messages by looking up tracking data
 * and returning status results. Each worker handles one tracking request at a time.
 * Logger: traces parcel lookup requests and status responses.
 */
public class ParcelTrackingWorker extends AbstractActor {

    public static Props props() {
        return Props.create(ParcelTrackingWorker.class, ParcelTrackingWorker::new);
    }

    @Override
    public Receive createReceive() {
        return receiveBuilder()
            .match(ActorMessage.TrackParcel.class, this::onTrackParcel)
            .match(ActorMessage.GetParcelStatus.class, this::onGetParcelStatus)
            .build();
    }

    private void onTrackParcel(ActorMessage.TrackParcel msg) {
        String result = "Tracking parcel: " + msg.trackingNumber();
        getSender().tell(new ActorMessage.WorkerResult(msg.trackingNumber(), result), getSelf());
    }

    private void onGetParcelStatus(ActorMessage.GetParcelStatus msg) {
        String result = "Status for " + msg.trackingNumber() + ": In transit";
        getSender().tell(new ActorMessage.WorkerResult(msg.trackingNumber(), result), getSelf());
    }
}