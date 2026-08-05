package com.divric.parceltracking.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * DTO for parcel tracking responses.
 * Contains the tracking number and the tracking result.
 */
@Schema(description = "Response payload for parcel tracking")
public class ParcelTrackResponse {

    @Schema(description = "The tracking number queried", example = "TRK-00001")
    private String trackingNumber;

    @Schema(description = "The tracking result details", example = "Package TRK-00001 is currently in transit from New York, NY to Los Angeles, CA. Estimated delivery: August 5, 2026.")
    private String result;

    public ParcelTrackResponse() {}

    public ParcelTrackResponse(String trackingNumber, String result) {
        this.trackingNumber = trackingNumber;
        this.result = result;
    }

    public String getTrackingNumber() {
        return trackingNumber;
    }

    public void setTrackingNumber(String trackingNumber) {
        this.trackingNumber = trackingNumber;
    }

    public String getResult() {
        return result;
    }

    public void setResult(String result) {
        this.result = result;
    }
}