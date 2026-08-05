package com.divric.parceltracking.controller;

import com.divric.parceltracking.dto.ParcelStatusResponse;
import com.divric.parceltracking.dto.ParcelTrackResponse;
import com.divric.parceltracking.engine.SupervisorActorEngine;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for parcel tracking operations.
 * Provides endpoints to track parcels and check their status directly,
 * bypassing the chat interface. Useful for testing and direct API access.
 */
@RestController
@RequestMapping("/api/parcels")
@Tag(name = "Parcels", description = "Parcel tracking operations — track parcels and check status directly")
public class ParcelController {

    private static final Logger log = LoggerFactory.getLogger(ParcelController.class);

    private final SupervisorActorEngine engine;

    public ParcelController(SupervisorActorEngine engine) {
        this.engine = engine;
    }

    @GetMapping("/track/{trackingNumber}")
    @Operation(
        summary = "Track a parcel",
        description = "Track a parcel by its tracking number. Returns the current location and delivery status."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Tracking information retrieved successfully",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = ParcelTrackResponse.class),
                examples = @ExampleObject(value = "{\"trackingNumber\":\"TRK-00001\",\"result\":\"Package TRK-00001 is currently in transit from New York, NY to Los Angeles, CA. Estimated delivery: August 5, 2026.\"}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Invalid tracking number",
            content = @Content
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — tracking failed",
            content = @Content
        )
    })
    public ResponseEntity<?> trackParcel(@PathVariable String trackingNumber) {
        try {
            String result = engine.trackParcel(trackingNumber);
            return ResponseEntity.ok(new ParcelTrackResponse(trackingNumber, result));
        } catch (Exception e) {
            log.error("Parcel tracking failed for {}: {}", trackingNumber, e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new ParcelTrackResponse(trackingNumber, "Tracking failed: " + e.getMessage()));
        }
    }

    @GetMapping("/status/{trackingNumber}")
    @Operation(
        summary = "Get parcel status",
        description = "Get the current status of a parcel by its tracking number."
    )
    @ApiResponses(value = {
        @ApiResponse(
            responseCode = "200",
            description = "Status retrieved successfully",
            content = @Content(mediaType = "application/json", schema = @Schema(implementation = ParcelStatusResponse.class),
                examples = @ExampleObject(value = "{\"trackingNumber\":\"TRK-00001\",\"status\":\"Package TRK-00001 is currently in transit. Last scanned at New York, NY distribution center.\"}"))
        ),
        @ApiResponse(
            responseCode = "400",
            description = "Invalid tracking number",
            content = @Content
        ),
        @ApiResponse(
            responseCode = "500",
            description = "Internal server error — status check failed",
            content = @Content
        )
    })
    public ResponseEntity<?> getParcelStatus(@PathVariable String trackingNumber) {
        try {
            String status = engine.getParcelStatus(trackingNumber);
            return ResponseEntity.ok(new ParcelStatusResponse(trackingNumber, status));
        } catch (Exception e) {
            log.error("Parcel status check failed for {}: {}", trackingNumber, e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new ParcelStatusResponse(trackingNumber, "Status check failed: " + e.getMessage()));
        }
    }
}