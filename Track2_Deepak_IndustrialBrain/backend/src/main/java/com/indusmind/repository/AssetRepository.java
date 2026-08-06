package com.indusmind.repository;

import com.indusmind.domain.Asset;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface AssetRepository extends JpaRepository<Asset, Long> {
    Optional<Asset> findByTagIgnoreCase(String tag);
    boolean existsByTagIgnoreCase(String tag);
}
