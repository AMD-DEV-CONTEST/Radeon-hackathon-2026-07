# WorldForge Human Character System

Generation 6 replaces PERSON sphere markers with contextual human characters.

## Resolution pipeline

PERSON entity
-> deterministic CharacterProfile
-> biome-aware clothing palette
-> optional `entity.properties.model_url`
-> GLB character when available
-> procedural humanoid fallback otherwise
-> proximity-aware nameplate

## Production characters

A PERSON entity may provide:

```json
{
  "model_url": "/worldforge/assets/characters/example.glb"
}
```

The model should use glTF/GLB, be centered at ground level, face the expected forward axis, and be optimized for real-time rendering.

The procedural human remains the safety fallback so missing character assets never make an entity disappear.

## Current scope

This generation provides human proportions, deterministic appearance, contextual clothing palettes, GLB loading infrastructure, and proximity labels. Photorealistic humans require production character models, textures, skeletal rigs, animations, facial systems, and LODs. Those are assets/content, not something primitive Three.js geometry can magically impersonate.
