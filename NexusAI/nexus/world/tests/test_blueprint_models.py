from nexus.world import BlueprintValue,ProvenanceType

def test_blueprint_value_tracks_evidence():
 v=BlueprintValue(value="desert",confidence=.9,provenance=ProvenanceType.SOURCE,evidence=["desert"])
 assert v.evidence==["desert"]
