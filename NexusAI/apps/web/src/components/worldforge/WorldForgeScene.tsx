"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  Environment,
  Float,
  Html,
  OrbitControls,
  PointerLockControls,
} from "@react-three/drei";
import type { LayoutData } from "./types";
import KnowledgeCity from "./KnowledgeCity";
import BiomeEnvironment from "./BiomeEnvironment";
import BiomeTerrain from "./BiomeTerrain";
import BiomeAtmosphere from "./BiomeAtmosphere";
import TerrainScatter from "./TerrainScatter";
import ProductionTerrainScatter from "./ProductionTerrainScatter";
import { productionEnvironmentAssetsEnabled } from "./environmentAssetAvailability";
import BiomeGroundDetail from "./BiomeGroundDetail";
import WorldCharacter from "./WorldCharacter";
import { getEnvironmentRenderSpec } from "./environmentApi";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import {
  getWorldForgeData,
  type WorldForgeData,
  type WorldForgeEntity,
} from "@/lib/api";
import { useSearchParams } from "next/navigation";
import { buildKnowledgeLayout, getWorldViewCamera } from "./layout";

type Mode = "explorer" | "world";
type Vec3 = [number, number, number];

const CITY_SIZE = 64;
const PLAYER_HEIGHT = 1.7;
const PLAYER_RADIUS = 0.38;
const WALK_SPEED = 5.5;
const SPRINT_SPEED = 9;
const JUMP_VELOCITY = 7;
const GRAVITY = 19;
type BuildingData = {
  position: Vec3;
  width: number;
  depth: number;
  height: number;
  rotation: number;
  seed: number;
};

type Collider = {
  x: number;
  z: number;
  halfW: number;
  halfD: number;
  rotation: number;
};

type PlayerState = {
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
};

function seeded(seed: number) {
  const x = Math.sin(seed * 917.31) * 43758.5453;
  return x - Math.floor(x);
}

function createCity() {
  const buildings: BuildingData[] = [];
  const colliders: Collider[] = [];
  let seed = 9;

  for (let gx = -24; gx <= 24; gx += 8) {
    for (let gz = -24; gz <= 24; gz += 8) {
      if (Math.abs(gx) < 6 && Math.abs(gz) < 6) continue;

      const offsetX = (seeded(seed + 1) - 0.5) * 1.5;
      const offsetZ = (seeded(seed + 2) - 0.5) * 1.5;
      const width = 2.5 + seeded(seed + 3) * 2.0;
      const depth = 2.4 + seeded(seed + 4) * 2.1;
      const height = 3 + seeded(seed + 5) * 9;
      const quarterTurn = Math.floor(seeded(seed + 6) * 4);
      const rotation = quarterTurn * (Math.PI / 2);

      // Some corner buildings get a subtle diagonal orientation.
      const diagonal =
        Math.abs(gx) >= 16 && Math.abs(gz) >= 16 && seeded(seed + 8) > 0.68;
      const finalRotation = diagonal
        ? rotation + (seeded(seed + 9) > 0.5 ? Math.PI / 8 : -Math.PI / 8)
        : rotation;

      const position: Vec3 = [gx + offsetX, 0, gz + offsetZ];

      buildings.push({
        position,
        width,
        depth,
        height,
        rotation: finalRotation,
        seed,
      });

      // For 90-degree rotations, swap footprint dimensions. Diagonal buildings
      // use a conservative square bound so collision remains reliable.
      const isQuarter = Math.abs(Math.sin(finalRotation * 2)) < 0.001;
      const rotated90 = Math.abs(Math.sin(finalRotation)) > 0.9;
      const boundW = isQuarter
        ? rotated90
          ? depth
          : width
        : Math.max(width, depth) * 1.18;
      const boundD = isQuarter
        ? rotated90
          ? width
          : depth
        : Math.max(width, depth) * 1.18;

      colliders.push({
        x: position[0],
        z: position[2],
        halfW: boundW / 2 + PLAYER_RADIUS,
        halfD: boundD / 2 + PLAYER_RADIUS,
        rotation: finalRotation,
      });

      seed += 17;
    }
  }

  return { buildings, colliders };
}

const CITY = createCity();

function normalizeEntityType(type: string) {
  return type.trim().toLowerCase();
}

function entityVisual(type: string) {
  const normalized = normalizeEntityType(type);
  if (["place", "location", "city", "country"].includes(normalized)) {
    return { color: "#34d399", emissive: "#059669", kind: "PLACE" };
  }
  if (["organization", "organisation", "company", "lab"].includes(normalized)) {
    return { color: "#c4b5fd", emissive: "#7c3aed", kind: "ORGANIZATION" };
  }
  if (["project", "system", "product"].includes(normalized)) {
    return { color: "#f0abfc", emissive: "#c026d3", kind: "PROJECT" };
  }
  if (["person", "character"].includes(normalized)) {
    return { color: "#fef08a", emissive: "#ca8a04", kind: "PERSON" };
  }
  return {
    color: "#93c5fd",
    emissive: "#2563eb",
    kind: normalized.toUpperCase() || "ENTITY",
  };
}

function KnowledgeEntityMarker({
  entity,
  position,
  environment,
}: {
  entity: WorldForgeEntity;
  position: Vec3;
  environment: EnvironmentRenderSpec | null;
}) {
  const visual = entityVisual(entity.entity_type);
  const prominence = Math.min(1.8, 1 + entity.connection_count * 0.12);

  if (visual.kind === "PERSON") {
    return (
      <WorldCharacter
        entity={entity}
        position={position}
        environment={environment}
      />
    );
  }

  return (
    <group position={position}>
      <mesh castShadow position={[0, 1.1 * prominence, 0]}>
        {visual.kind === "PERSON" ? (
          <sphereGeometry args={[0.42 * prominence, 24, 24]} />
        ) : visual.kind === "PLACE" ? (
          <cylinderGeometry
            args={[0.8 * prominence, 1.05 * prominence, 1.6 * prominence, 10]}
          />
        ) : (
          <boxGeometry
            args={[1.5 * prominence, 2.2 * prominence, 1.5 * prominence]}
          />
        )}
        <meshStandardMaterial
          color={visual.color}
          emissive={visual.emissive}
          emissiveIntensity={1.8}
          metalness={0.45}
          roughness={0.3}
        />
      </mesh>

      <pointLight
        position={[0, 1.8 * prominence, 0]}
        intensity={4}
        distance={5}
        color={visual.color}
      />

      <Html position={[0, 2.8 * prominence, 0]} center distanceFactor={12}>
        <div className="pointer-events-none whitespace-nowrap rounded-md border border-white/10 bg-black/70 px-2 py-1 text-[10px] text-cyan-50 backdrop-blur-md">
          <div className="font-semibold">{entity.name}</div>
          <div className="mt-0.5 text-[8px] uppercase tracking-wider text-white/45">
            {visual.kind} · {entity.connection_count} links
          </div>
        </div>
      </Html>
    </group>
  );
}

function KnowledgeLayer({
  data,
  environment,
}: {
  data: WorldForgeData | null;
  environment: EnvironmentRenderSpec | null;
}) {
  const layout = useMemo(() => {
    const positions = new Map<string, Vec3>();
    const districts = new Map<
      string,
      { id: string; name: string; position: Vec3; members: string[] }
    >();

    if (!data || data.entities.length === 0) {
      return {
        positions,
        districts: [] as Array<{
          id: string;
          name: string;
          position: Vec3;
          members: string[];
        }>,
      };
    }

    const byId = new Map(data.entities.map((entity) => [entity.id, entity]));
    const placeTypes = new Set(["place", "location", "city", "country"]);

    const placeEntities = data.entities.filter((entity) =>
      placeTypes.has(normalizeEntityType(entity.entity_type)),
    );

    // Places become district anchors.
    placeEntities.forEach((place, index) => {
      const angle =
        (index / Math.max(placeEntities.length, 1)) * Math.PI * 2 - Math.PI / 4;
      const radius = placeEntities.length === 1 ? 0 : 17;
      const position: Vec3 = [
        Math.cos(angle) * radius,
        0.12,
        Math.sin(angle) * radius,
      ];
      positions.set(place.id, position);
      districts.set(place.id, {
        id: place.id,
        name: place.name,
        position,
        members: [],
      });
    });

    const placementRelations = new Set([
      "LIVES_IN",
      "LOCATED_IN",
      "BASED_IN",
      "WORKS_AT",
      "WORKS_IN",
      "VISITED",
    ]);

    // Entities connected to places are clustered around those districts.
    for (const relationship of data.relationships) {
      const type = relationship.relationship_type.toUpperCase();
      if (!placementRelations.has(type)) continue;

      const source = byId.get(relationship.source_entity_id);
      const target = byId.get(relationship.target_entity_id);
      if (!source || !target) continue;

      const sourceIsPlace = placeTypes.has(
        normalizeEntityType(source.entity_type),
      );
      const targetIsPlace = placeTypes.has(
        normalizeEntityType(target.entity_type),
      );

      const place = sourceIsPlace ? source : targetIsPlace ? target : null;
      const member = sourceIsPlace ? target : targetIsPlace ? source : null;
      if (!place || !member) continue;

      const district = districts.get(place.id);
      if (district && !district.members.includes(member.id)) {
        district.members.push(member.id);
      }
    }

    // Place district members around their anchor.
    districts.forEach((district) => {
      district.members.forEach((memberId, index) => {
        if (positions.has(memberId)) return;
        const count = Math.max(district.members.length, 1);
        const angle = (index / count) * Math.PI * 2;
        const radius = 3.5 + (index % 2) * 1.4;
        positions.set(memberId, [
          district.position[0] + Math.cos(angle) * radius,
          0.12,
          district.position[2] + Math.sin(angle) * radius,
        ]);
      });
    });

    // Organizations/projects can pull directly related entities into local clusters.
    const hubTypes = new Set([
      "organization",
      "organisation",
      "company",
      "lab",
      "project",
      "system",
      "product",
    ]);

    const hubRelations = new Set([
      "WORKS_WITH",
      "MAINTAINS",
      "ADVISES",
      "CREATED",
      "CONNECTED_TO",
      "CONTAINS",
      "LEADS",
    ]);

    let hubIndex = 0;
    for (const entity of data.entities) {
      if (positions.has(entity.id)) continue;
      if (!hubTypes.has(normalizeEntityType(entity.entity_type))) continue;

      const angle =
        (hubIndex / Math.max(data.entities.length, 1)) * Math.PI * 2 + 0.7;
      const radius = 9 + (hubIndex % 3) * 2.5;
      positions.set(entity.id, [
        Math.cos(angle) * radius,
        0.12,
        Math.sin(angle) * radius,
      ]);
      hubIndex += 1;
    }

    // Place remaining entities near a connected hub when possible.
    for (const relationship of data.relationships) {
      if (!hubRelations.has(relationship.relationship_type.toUpperCase()))
        continue;

      const sourcePosition = positions.get(relationship.source_entity_id);
      const targetPosition = positions.get(relationship.target_entity_id);

      if (sourcePosition && !targetPosition) {
        const seed = relationship.target_entity_id.charCodeAt(0) || 1;
        const angle = (seed % 12) * (Math.PI / 6);
        positions.set(relationship.target_entity_id, [
          sourcePosition[0] + Math.cos(angle) * 3.2,
          0.12,
          sourcePosition[2] + Math.sin(angle) * 3.2,
        ]);
      } else if (targetPosition && !sourcePosition) {
        const seed = relationship.source_entity_id.charCodeAt(0) || 1;
        const angle = (seed % 12) * (Math.PI / 6);
        positions.set(relationship.source_entity_id, [
          targetPosition[0] + Math.cos(angle) * 3.2,
          0.12,
          targetPosition[2] + Math.sin(angle) * 3.2,
        ]);
      }
    }

    // Deterministic fallback ring for disconnected entities.
    const remaining = data.entities.filter(
      (entity) => !positions.has(entity.id),
    );
    remaining.forEach((entity, index) => {
      const angle = (index / Math.max(remaining.length, 1)) * Math.PI * 2;
      positions.set(entity.id, [
        Math.cos(angle) * 23,
        0.12,
        Math.sin(angle) * 23,
      ]);
    });

    return {
      positions,
      districts: Array.from(districts.values()),
    };
  }, [data]);

  if (!data) return null;

  return (
    <>
      {/* District boundaries derived from place entities. */}
      {layout.districts.map((district) => (
        <group key={`district-${district.id}`} position={district.position}>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
            <ringGeometry args={[5.2, 5.35, 64]} />
            <meshBasicMaterial
              color="#34d399"
              transparent
              opacity={0.35}
              side={THREE.DoubleSide}
            />
          </mesh>
          <Html position={[0, 0.25, 0]} center distanceFactor={18}>
            <div className="pointer-events-none whitespace-nowrap rounded-full border border-emerald-300/20 bg-black/60 px-3 py-1 text-[9px] uppercase tracking-[0.18em] text-emerald-200 backdrop-blur-md">
              {district.name} District
            </div>
          </Html>
        </group>
      ))}

      {/* Relationships become spatial links between graph-driven positions. */}
      {data.relationships.map((relationship) => {
        const source = layout.positions.get(relationship.source_entity_id);
        const target = layout.positions.get(relationship.target_entity_id);
        if (!source || !target) return null;

        const start = new THREE.Vector3(...source);
        const end = new THREE.Vector3(...target);
        const midpoint = start.clone().add(end).multiplyScalar(0.5);
        midpoint.y += 0.18;
        const length = start.distanceTo(end);
        const direction = end.clone().sub(start).normalize();
        const quaternion = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 1, 0),
          direction,
        );

        return (
          <mesh
            key={relationship.id}
            position={midpoint}
            quaternion={quaternion}
          >
            <cylinderGeometry args={[0.035, 0.035, length, 8]} />
            <meshBasicMaterial color="#22d3ee" transparent opacity={0.42} />
          </mesh>
        );
      })}

      {data.entities.map((entity) => {
        const position = layout.positions.get(entity.id);
        if (!position) return null;
        return (
          <KnowledgeEntityMarker
            key={entity.id}
            entity={entity}
            position={position}
            environment={environment}
          />
        );
      })}
    </>
  );
}

function Building({ data }: { data: BuildingData }) {
  const { position, width, depth, height, rotation, seed } = data;
  const rows = Math.max(2, Math.floor(height / 1.25));
  const windows = [];

  for (let row = 0; row < rows; row++) {
    for (const side of [-1, 1]) {
      windows.push(
        <mesh
          key={`f-${row}-${side}`}
          position={[side * width * 0.23, 0.75 + row * 1.03, depth / 2 + 0.012]}
        >
          <planeGeometry args={[width * 0.2, 0.32]} />
          <meshBasicMaterial
            color={seeded(seed + row * 4 + side) > 0.32 ? "#67e8f9" : "#172554"}
            transparent
            opacity={0.82}
          />
        </mesh>,
      );
    }
  }

  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <mesh castShadow receiveShadow position={[0, height / 2, 0]}>
        <boxGeometry args={[width, height, depth]} />
        <meshStandardMaterial
          color={seeded(seed) > 0.48 ? "#111827" : "#070d18"}
          metalness={0.5}
          roughness={0.42}
        />
      </mesh>

      {windows}

      <mesh position={[0, height + 0.055, 0]}>
        <boxGeometry args={[width * 0.72, 0.11, depth * 0.72]} />
        <meshStandardMaterial
          color="#67e8f9"
          emissive="#0891b2"
          emissiveIntensity={2}
        />
      </mesh>
    </group>
  );
}

function Roads() {
  const items = [];
  for (let i = -26; i <= 26; i += 8) {
    items.push(
      <mesh key={`rx-${i}`} position={[0, 0.024, i]} receiveShadow>
        <boxGeometry args={[CITY_SIZE, 0.05, 2.4]} />
        <meshStandardMaterial color="#030711" roughness={0.95} />
      </mesh>,
      <mesh key={`rz-${i}`} position={[i, 0.025, 0]} receiveShadow>
        <boxGeometry args={[2.4, 0.05, CITY_SIZE]} />
        <meshStandardMaterial color="#030711" roughness={0.95} />
      </mesh>,
    );
  }
  return <>{items}</>;
}

function NexusCore() {
  return (
    <>
      <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.25, 3.38, 96]} />
        <meshBasicMaterial
          color="#22d3ee"
          transparent
          opacity={0.82}
          side={THREE.DoubleSide}
        />
      </mesh>

      <Float speed={2.2} rotationIntensity={0.45} floatIntensity={0.65}>
        <mesh position={[0, 2.8, 0]}>
          <icosahedronGeometry args={[0.92, 2]} />
          <meshStandardMaterial
            color="#a5f3fc"
            emissive="#06b6d4"
            emissiveIntensity={3.6}
            metalness={0.65}
            roughness={0.12}
          />
        </mesh>
      </Float>

      <pointLight
        position={[0, 3, 0]}
        intensity={28}
        distance={18}
        color="#22d3ee"
      />
    </>
  );
}

function isBlocked(x: number, z: number) {
  // Keep the Explorer inside the playable WorldForge area.
  const WORLD_MARGIN = 1.5;

  if (
    Math.abs(x) > CITY_SIZE / 2 - WORLD_MARGIN ||
    Math.abs(z) > CITY_SIZE / 2 - WORLD_MARGIN
  ) {
    return true;
  }

  // Legacy CITY.colliders belonged to the old procedural skyscraper city.
  // KnowledgeCity now owns the visible semantic environment, so those
  // invisible colliders must no longer affect Explorer movement.
  return false;
}

function ExplorerController({
  enabled,
  onLockChange,
  playerState,
  requestLock,
  onLockRequestHandled,
}: {
  enabled: boolean;
  onLockChange: (locked: boolean) => void;
  playerState: React.MutableRefObject<PlayerState>;
  requestLock: number;
  onLockRequestHandled: () => void;
}) {
  const { camera } = useThree();
  const keys = useRef<Record<string, boolean>>({});
  const velocityY = useRef(0);
  const grounded = useRef(true);
  const initialized = useRef(false);
  const controlsRef = useRef<any>(null);

  const forward = useMemo(() => new THREE.Vector3(), []);
  const right = useMemo(() => new THREE.Vector3(), []);
  const movement = useMemo(() => new THREE.Vector3(), []);

  useEffect(() => {
    if (!enabled) return;

    if (!initialized.current) {
      camera.position.set(0, PLAYER_HEIGHT, 11);
      camera.lookAt(0, PLAYER_HEIGHT, 0);
      playerState.current.position.copy(camera.position);
      playerState.current.quaternion.copy(camera.quaternion);
      initialized.current = true;
    } else {
      camera.position.copy(playerState.current.position);
      camera.quaternion.copy(playerState.current.quaternion);
    }
  }, [enabled, camera, playerState]);

  useEffect(() => {
    if (!enabled || requestLock === 0) return;

    // PointerLockControls is now mounted and owns the lock lifecycle.
    // Calling its lock() method ensures mouse-look listeners and internal
    // state are synchronized, unlike directly locking the canvas.
    controlsRef.current?.lock();
    onLockRequestHandled();
  }, [enabled, requestLock, onLockRequestHandled]);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      keys.current[event.code] = true;

      if (
        enabled &&
        event.code === "Space" &&
        grounded.current &&
        document.pointerLockElement
      ) {
        velocityY.current = JUMP_VELOCITY;
        grounded.current = false;
        event.preventDefault();
      }
    };

    const up = (event: KeyboardEvent) => {
      keys.current[event.code] = false;
    };

    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);

    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [enabled]);

  useFrame((_, delta) => {
    if (!enabled) return;

    const dt = Math.min(delta, 0.05);
    const speed =
      keys.current.ShiftLeft || keys.current.ShiftRight
        ? SPRINT_SPEED
        : WALK_SPEED;

    camera.getWorldDirection(forward);
    forward.y = 0;
    forward.normalize();

    right.crossVectors(forward, camera.up).normalize();

    movement.set(0, 0, 0);
    if (keys.current.KeyW) movement.add(forward);
    if (keys.current.KeyS) movement.sub(forward);
    if (keys.current.KeyD) movement.add(right);
    if (keys.current.KeyA) movement.sub(right);

    if (movement.lengthSq() > 0) {
      movement.normalize().multiplyScalar(speed * dt);

      const nextX = camera.position.x + movement.x;
      const nextZ = camera.position.z + movement.z;

      if (!isBlocked(nextX, camera.position.z)) camera.position.x = nextX;
      if (!isBlocked(camera.position.x, nextZ)) camera.position.z = nextZ;
    }

    if (!grounded.current || velocityY.current !== 0) {
      velocityY.current -= GRAVITY * dt;
      camera.position.y += velocityY.current * dt;

      if (camera.position.y <= PLAYER_HEIGHT) {
        camera.position.y = PLAYER_HEIGHT;
        velocityY.current = 0;
        grounded.current = true;
      }
    } else {
      camera.position.y = PLAYER_HEIGHT;
    }

    playerState.current.position.copy(camera.position);
    playerState.current.quaternion.copy(camera.quaternion);
  });

  if (!enabled) return null;

  return (
    <PointerLockControls
      ref={controlsRef}
      makeDefault
      onLock={() => onLockChange(true)}
      onUnlock={() => onLockChange(false)}
    />
  );
}

function PlayerWorldMarker({
  visible,
  playerState,
}: {
  visible: boolean;
  playerState: React.MutableRefObject<PlayerState>;
}) {
  const group = useRef<THREE.Group>(null);
  const arrow = useRef<THREE.Group>(null);
  const facing = useMemo(() => new THREE.Vector3(0, 0, -1), []);
  const euler = useMemo(() => new THREE.Euler(), []);

  useFrame((state) => {
    if (!visible || !group.current) return;

    const position = playerState.current.position;
    group.current.position.set(position.x, 0.08, position.z);

    // Convert the saved first-person camera quaternion into a horizontal
    // direction marker so World View shows where the player was facing.
    facing.set(0, 0, -1).applyQuaternion(playerState.current.quaternion);
    facing.y = 0;

    if (facing.lengthSq() > 0.0001 && arrow.current) {
      facing.normalize();
      const yaw = Math.atan2(-facing.x, -facing.z);
      arrow.current.rotation.y = yaw;
    }

    // Subtle pulse makes the marker easy to find without becoming a nightclub.
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 3) * 0.08;
    group.current.scale.setScalar(pulse);
  });

  if (!visible) return null;

  return (
    <group ref={group}>
      {/* Ground location ring */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.55, 0.72, 48]} />
        <meshBasicMaterial
          color="#67e8f9"
          transparent
          opacity={0.95}
          side={THREE.DoubleSide}
          depthTest={false}
        />
      </mesh>

      {/* Inner location disc */}
      <mesh position={[0, 0.015, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.18, 32]} />
        <meshBasicMaterial color="#ecfeff" depthTest={false} />
      </mesh>

      {/* Direction arrow */}
      <group ref={arrow} position={[0, 0.06, 0]}>
        <mesh position={[0, 0, -0.82]} rotation={[-Math.PI / 2, 0, 0]}>
          <coneGeometry args={[0.22, 0.65, 3]} />
          <meshBasicMaterial color="#a5f3fc" depthTest={false} />
        </mesh>
      </group>

      {/* Vertical beacon */}
      <mesh position={[0, 5, 0]}>
        <cylinderGeometry args={[0.035, 0.12, 10, 12]} />
        <meshBasicMaterial
          color="#22d3ee"
          transparent
          opacity={0.5}
          depthWrite={false}
        />
      </mesh>

      <pointLight
        position={[0, 0.6, 0]}
        intensity={8}
        distance={5}
        color="#22d3ee"
      />
    </group>
  );
}

function InteractiveWorldView({
  enabled,
  layout,
}: {
  enabled: boolean;
  layout: LayoutData;
}) {
  const { camera } = useThree();
  const cameraPreset = useMemo(() => getWorldViewCamera(layout), [layout]);
  const controls = useRef<any>(null);

  useEffect(() => {
    if (!enabled) return;

    camera.position.set(...cameraPreset.position);

    controls.current?.target.set(...cameraPreset.target);

    controls.current?.update();
  }, [enabled, camera, cameraPreset]);

  if (!enabled) return null;

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableDamping
      dampingFactor={0.055}
      enableRotate
      enableZoom
      enablePan
      minDistance={cameraPreset.minDistance}
      maxDistance={cameraPreset.maxDistance}
      maxPolarAngle={Math.PI / 2.02}
      target={cameraPreset.target}
    />
  );
}

function World({
  mode,
  onLockChange,
  playerState,
  explorerLockRequest,
  onExplorerLockRequestHandled,
  knowledgeData,
  environmentSpec,
  layout,
}: {
  mode: Mode;
  onLockChange: (locked: boolean) => void;
  playerState: React.MutableRefObject<PlayerState>;
  explorerLockRequest: number;
  onExplorerLockRequestHandled: () => void;
  knowledgeData: WorldForgeData | null;
  environmentSpec: EnvironmentRenderSpec | null;
  layout: LayoutData;
}) {
  return (
    <>
      <BiomeEnvironment spec={environmentSpec} />
      <BiomeAtmosphere spec={environmentSpec} />
      <BiomeTerrain spec={environmentSpec} size={CITY_SIZE + 32} />
      <BiomeGroundDetail spec={environmentSpec} />
      {productionEnvironmentAssetsEnabled(environmentSpec) ? (
        <ProductionTerrainScatter spec={environmentSpec} />
      ) : (
        <TerrainScatter spec={environmentSpec} />
      )}
      {!knowledgeData && <Roads />}
      {knowledgeData ? (
        <>
          <KnowledgeCity data={knowledgeData} />
          <KnowledgeLayer data={knowledgeData} environment={environmentSpec} />
        </>
      ) : (
        CITY.buildings.map((data) => (
          <Building
            key={`${data.position[0]}-${data.position[2]}`}
            data={data}
          />
        ))
      )}
      {!knowledgeData && (
        <gridHelper
          args={[CITY_SIZE, 64, "#0e7490", "#0f172a"]}
          position={[0, 0.01, 0]}
        />
      )}
      <PlayerWorldMarker visible={mode === "world"} playerState={playerState} />
      <ExplorerController
        enabled={mode === "explorer"}
        onLockChange={onLockChange}
        playerState={playerState}
        requestLock={explorerLockRequest}
        onLockRequestHandled={onExplorerLockRequestHandled}
      />
      <InteractiveWorldView enabled={mode === "world"} layout={layout} />{" "}
    </>
  );
}

export default function WorldForgeScene() {
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>("explorer");
  const [locked, setLocked] = useState(false);
  const [hasEntered, setHasEntered] = useState(false);
  const [explorerLockRequest, setExplorerLockRequest] = useState(0);
  const [knowledgeData, setKnowledgeData] = useState<WorldForgeData | null>(
    null,
  );
  const [knowledgeStatus, setKnowledgeStatus] = useState<
    "idle" | "loading" | "loaded" | "error"
  >("idle");
  const [environmentSpec, setEnvironmentSpec] =
    useState<EnvironmentRenderSpec | null>(null);

  const layout = useMemo(
    () => buildKnowledgeLayout(knowledgeData),
    [knowledgeData],
  );

  const playerState = useRef<PlayerState>({
    position: new THREE.Vector3(0, PLAYER_HEIGHT, 11),
    quaternion: new THREE.Quaternion(),
  });

  useEffect(() => {
    const loadKnowledge = async () => {
      const urlWorldId = searchParams.get("world_id");

      const fallbackWorldId =
        process.env.NEXT_PUBLIC_WORLDFORGE_WORLD_ID?.trim();

      const worldId = urlWorldId || fallbackWorldId;

      if (!worldId) {
        setKnowledgeStatus("idle");
        return;
      }

      setKnowledgeStatus("loading");

      try {
        const data = await getWorldForgeData(worldId);

        setKnowledgeData(data);
        try {
          const spec = await getEnvironmentRenderSpec(worldId, data);
          setEnvironmentSpec(spec);
        } catch (environmentError) {
          console.warn(
            "Using generic WorldForge environment:",
            environmentError,
          );
          setEnvironmentSpec(null);
        }
        setKnowledgeStatus("loaded");
      } catch (error) {
        console.error("Unable to load WorldForge knowledge:", error);

        setKnowledgeStatus("error");
      }
    };

    loadKnowledge();
  }, [searchParams]);

  const toggleMode = () => {
    if (mode === "explorer") {
      playerState.current.position.y = Math.max(
        playerState.current.position.y,
        PLAYER_HEIGHT,
      );
      document.exitPointerLock?.();
      setMode("world");
      return;
    }

    // Mount Explorer + PointerLockControls first. The controller effect then
    // calls its own lock() method, so mouse-look and WASD resume together.
    setMode("explorer");

    if (hasEntered) {
      setExplorerLockRequest((value) => value + 1);
    }
  };

  const handleExplorerLockRequest = () => {
    setExplorerLockRequest(0);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.code === "KeyM") {
        event.preventDefault();
        toggleMode();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="fixed inset-0 h-screen w-screen overflow-hidden bg-black">
      <Canvas
        shadows
        camera={{ position: [0, PLAYER_HEIGHT, 11], fov: 72 }}
        gl={{ antialias: true }}
        dpr={[1, 1.6]}
      >
        <World
          layout={layout}
          mode={mode}
          onLockChange={setLocked}
          playerState={playerState}
          explorerLockRequest={explorerLockRequest}
          onExplorerLockRequestHandled={handleExplorerLockRequest}
          knowledgeData={knowledgeData}
          environmentSpec={environmentSpec}
        />
      </Canvas>

      <div className="pointer-events-none absolute inset-0 z-10">
        <div className="absolute left-6 top-5 rounded-xl border border-white/10 bg-black/35 px-4 py-3 backdrop-blur-md">
          <p className="text-[10px] font-semibold uppercase tracking-[0.35em] text-cyan-200/80">
            NexusAI · WorldForge
          </p>
          <p className="mt-1 text-[11px] text-white/45">
            {mode === "explorer"
              ? "Explorer Mode"
              : "Interactive World View · Drag · Zoom · Pan"}
          </p>
        </div>

        {mode === "explorer" && locked && (
          <div className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2">
            <span className="absolute left-1/2 top-0 h-4 w-px -translate-x-1/2 bg-cyan-100/80" />
            <span className="absolute left-0 top-1/2 h-px w-4 -translate-y-1/2 bg-cyan-100/80" />
          </div>
        )}

        <div className="absolute bottom-6 left-6 rounded-xl border border-white/10 bg-black/45 px-4 py-3 text-[11px] text-white/55 backdrop-blur-md">
          {mode === "explorer" ? (
            <>
              <p>
                <span className="text-cyan-200">WASD</span> Move ·{" "}
                <span className="text-cyan-200">Shift</span> Sprint ·{" "}
                <span className="text-cyan-200">Space</span> Jump
              </p>
              <p className="mt-1">
                <span className="text-cyan-200">Mouse</span> Look ·{" "}
                <span className="text-cyan-200">M</span> World View ·{" "}
                <span className="text-cyan-200">Esc</span> Release
              </p>
            </>
          ) : (
            <>
              <p>Drag Rotate · Right-drag Pan · Scroll Zoom</p>
              <p className="mt-1">
                <span className="text-cyan-200">M</span> Resume Explorer
              </p>
              <p className="mt-2 border-t border-white/10 pt-2">
                <span className="text-cyan-200">◉</span> YOU · Beacon marks your
                Explorer position
              </p>
            </>
          )}
        </div>

        <div className="absolute bottom-6 right-6 text-right text-[11px] text-white/45">
          <p>WORLD · NEXUSAI</p>
          <p className="mt-1">
            {knowledgeData
              ? `${knowledgeData.entities.length} SEMANTIC STRUCTURES`
              : `${CITY.buildings.length} STRUCTURES`}
          </p>
          <p className="mt-1 text-cyan-200/70">
            {knowledgeStatus === "loaded"
              ? `${knowledgeData?.entities.length ?? 0} KNOWLEDGE ENTITIES · ${knowledgeData?.relationships.length ?? 0} LINKS`
              : knowledgeStatus === "loading"
                ? "LOADING KNOWLEDGE..."
                : knowledgeStatus === "error"
                  ? "KNOWLEDGE API OFFLINE"
                  : "KNOWLEDGE WORLD ID NOT CONFIGURED"}
          </p>
        </div>
      </div>

      {mode === "explorer" && !hasEntered && (
        <button
          className="absolute left-1/2 top-1/2 z-20 -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-cyan-300/25 bg-black/70 px-8 py-5 text-center backdrop-blur-xl transition hover:border-cyan-200/50"
          onClick={() => {
            setHasEntered(true);
            document.querySelector("canvas")?.requestPointerLock();
          }}
        >
          <span className="block text-xs font-semibold uppercase tracking-[0.3em] text-cyan-200">
            Enter WorldForge
          </span>
          <span className="mt-2 block text-[11px] text-white/45">
            Click once to enter · WASD + Mouse · Space to jump
          </span>
        </button>
      )}

      {mode === "explorer" &&
        hasEntered &&
        !locked &&
        explorerLockRequest === 0 && (
          <button
            className="absolute left-1/2 top-1/2 z-20 -translate-x-1/2 -translate-y-1/2 rounded-xl border border-white/10 bg-black/65 px-6 py-4 text-xs text-cyan-100/80 backdrop-blur-md"
            onClick={() =>
              document.querySelector("canvas")?.requestPointerLock()
            }
          >
            Resume Explorer
          </button>
        )}

      <button
        className="absolute right-6 top-5 z-20 rounded-full border border-white/10 bg-black/40 px-4 py-2 text-xs text-cyan-100/80 backdrop-blur-md transition hover:bg-white/10"
        onClick={toggleMode}
      >
        {mode === "explorer" ? "World View [M]" : "Explorer Mode [M]"}
      </button>

      <a
        href="/"
        className="absolute right-6 top-16 z-20 text-[11px] text-white/45 transition hover:text-cyan-100"
      >
        ← Return to Nexus
      </a>
    </div>
  );
}
