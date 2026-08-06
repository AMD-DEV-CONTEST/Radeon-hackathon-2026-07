from nexus.world import WorldBlueprint, WorldBlueprintEngine

class BlueprintService:
    """Application boundary around deterministic world-blueprint generation."""

    def __init__(self, engine: WorldBlueprintEngine | None = None):
        self.engine = engine or WorldBlueprintEngine()

    def generate(self, text: str) -> WorldBlueprint:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Blueprint source text cannot be empty")
        return self.engine.generate(normalized)
