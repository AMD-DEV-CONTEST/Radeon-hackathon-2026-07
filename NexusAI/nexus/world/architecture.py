from .blueprint_models import ArchitectureBlueprint, ArchitectureStyle, BlueprintValue
from .context import ContextEvidence

STYLE_TERMS={
 ArchitectureStyle.ANCIENT:{"ancient","temple","ruins","sandstone"},
 ArchitectureStyle.MEDIEVAL:{"medieval","castle","fortress","kingdom","timber"},
 ArchitectureStyle.MODERN:{"modern","apartment","concrete","office","highway"},
 ArchitectureStyle.FUTURISTIC:{"futuristic","cyberpunk","spaceship","neon","colony"},
 ArchitectureStyle.RURAL:{"village","farm","cottage","rural"},
 ArchitectureStyle.INDUSTRIAL:{"factory","warehouse","industrial","refinery"},
}
MATERIALS={"sandstone","stone","timber","wood","brick","concrete","steel","glass","ice"}

def infer_architecture(context:ContextEvidence)->ArchitectureBlueprint:
    best=ArchitectureStyle.GENERIC; hits:list[str]=[]
    for style,terms in STYLE_TERMS.items():
        current=sorted(context.tokens&terms)
        if len(current)>len(hits):best,hits=style,current
    confidence=.3 if not hits else min(.92,.55+.12*len(hits))
    materials=sorted(context.tokens&MATERIALS)
    settlement="city" if context.tokens&{"city","metropolis","urban"} else "village" if "village" in context.tokens else None
    return ArchitectureBlueprint(style=BlueprintValue(value=best.value,confidence=confidence,evidence=hits),materials=materials,settlement_type=settlement)
