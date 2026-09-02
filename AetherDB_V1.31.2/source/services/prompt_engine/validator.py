"""Validation."""
RULES=["Output ONLY valid JSON","只输出JSON格式"]
def validate_prompt(p):
    w=[r for r in RULES if r not in p]
    return{"valid":len(w)==0,"warnings":w}
