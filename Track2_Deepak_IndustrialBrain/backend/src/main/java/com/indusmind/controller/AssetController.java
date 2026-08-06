package com.indusmind.controller;

import com.indusmind.domain.Asset;
import com.indusmind.repository.AssetRepository;
import com.indusmind.service.AuditService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/registry/assets")
public class AssetController {
    private final AssetRepository assets;
    private final AuditService audit;

    public AssetController(AssetRepository assets, AuditService audit) {
        this.assets = assets; this.audit = audit;
    }

    @GetMapping
    public List<Asset> list() { return assets.findAll(); }

    @GetMapping("/{tag}")
    public ResponseEntity<?> get(@PathVariable String tag) {
        return assets.findByTagIgnoreCase(tag)
                .<ResponseEntity<?>>map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping
    public ResponseEntity<?> create(@Valid @RequestBody AssetRequest request) {
        if (assets.existsByTagIgnoreCase(request.tag())) {
            return ResponseEntity.status(409).body(Map.of("message", "Asset tag already registered: " + request.tag()));
        }
        Asset asset = new Asset();
        apply(asset, request);
        asset.setTag(request.tag().toUpperCase());
        assets.save(asset);
        audit.record("ASSET_CREATED", "asset", asset.getTag(), request.name());
        return ResponseEntity.status(201).body(asset);
    }

    @PutMapping("/{id}")
    public ResponseEntity<?> update(@PathVariable Long id, @Valid @RequestBody AssetRequest request) {
        return assets.findById(id).<ResponseEntity<?>>map(asset -> {
            apply(asset, request);
            asset.setUpdatedAt(java.time.Instant.now());
            assets.save(asset);
            audit.record("ASSET_UPDATED", "asset", asset.getTag(), request.name());
            return ResponseEntity.ok(asset);
        }).orElseGet(() -> ResponseEntity.notFound().build());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<?> delete(@PathVariable Long id) {
        return assets.findById(id).<ResponseEntity<?>>map(asset -> {
            assets.delete(asset);
            audit.record("ASSET_DELETED", "asset", asset.getTag(), null);
            return ResponseEntity.noContent().build();
        }).orElseGet(() -> ResponseEntity.notFound().build());
    }

    private void apply(Asset asset, AssetRequest request) {
        asset.setName(request.name());
        asset.setLocation(request.location());
        asset.setCriticality(request.criticality());
        asset.setManufacturer(request.manufacturer());
        asset.setInstallDate(request.installDate());
        asset.setNotes(request.notes());
    }

    public record AssetRequest(
            @NotBlank String tag,
            String name,
            String location,
            String criticality,
            String manufacturer,
            LocalDate installDate,
            String notes) {}
}
