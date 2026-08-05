package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for parcel status responses.
 * Contains the tracking number and the current status result.
 */
@Schema(description = "Response payload for parcel status check")
public class ParcelStatusResponse {

    @Schema(description = "The tracking number queried", example = "TRK-00001")
    private String trackingNumber;

    @Schema(description = "The current status of the parcel", example = "Package TRK-00001 is currently in transit. Last scanned at New York, NY distribution center.")
    private String status;

    public ParcelStatusResponse() {}

    public ParcelStatusResponse(String trackingNumber, String status) {
        this.trackingNumber = trackingNumber;
        this.status = status;
    }

    public String getTrackingNumber() {
        return trackingNumber;
    }

    public void setTrackingNumber(String trackingNumber) {
        this.trackingNumber = trackingNumber;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}