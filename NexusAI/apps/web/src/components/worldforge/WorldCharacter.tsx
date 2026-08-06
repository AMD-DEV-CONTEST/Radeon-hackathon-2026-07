"use client";

import { Suspense, useMemo } from "react";
import type { WorldForgeEntity } from "@/lib/api";
import type { EnvironmentRenderSpec } from "./environmentTypes";
import { buildCharacterProfile } from "./characterProfile";
import HumanModel from "./HumanModel";
import ProceduralHuman from "./ProceduralHuman";
import CharacterNameplate from "./CharacterNameplate";
import type { Vec3 } from "./types";

export default function WorldCharacter({
  entity,
  position,
  environment,
  selected = false,
  dimmed = false,
}: {
  entity: WorldForgeEntity;
  position: Vec3;
  environment: EnvironmentRenderSpec | null;
  selected?: boolean;
  dimmed?: boolean;
}) {
  const profile = useMemo(
    () => buildCharacterProfile(entity, environment),
    [entity, environment],
  );

  return (
    <group position={position}>
      {profile.modelUrl ? (
        <Suspense fallback={<ProceduralHuman profile={profile} selected={selected} dimmed={dimmed} />}>
          <HumanModel url={profile.modelUrl} scale={profile.height} />
        </Suspense>
      ) : (
        <ProceduralHuman profile={profile} selected={selected} dimmed={dimmed} />
      )}
      <CharacterNameplate entity={entity} position={[0, 0, 0]} />
    </group>
  );
}
