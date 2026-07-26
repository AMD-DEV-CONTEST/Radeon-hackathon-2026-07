package com.divric.parceltracking.repository;

import com.divric.parceltracking.model.OrderTracking;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;


public interface OrderRepository extends JpaRepository<OrderTracking, Long> {

    Optional<OrderTracking> findByTrackingNumber(String trackingNumber);
}