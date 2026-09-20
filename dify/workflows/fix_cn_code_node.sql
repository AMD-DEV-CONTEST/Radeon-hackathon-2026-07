BEGIN;
UPDATE workflows w
SET graph = jsonb_set(w.graph::jsonb, '{nodes}', (
  SELECT jsonb_agg(CASE WHEN node->>'id' = '1785411748531' THEN
    jsonb_set(node, '{data,code}', to_jsonb($code$import json
import re

def main(arg1: str):
    try:
        text = re.sub(r"^\s*assistant\s*$", "", (arg1 or "").strip(), flags=re.MULTILINE)
        candidate = text[text.find("{"):text.rfind("}") + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            marker = text.find('"strategy"')
            strategy_start = text.find("{", marker)
            strategy_only, _ = json.JSONDecoder().raw_decode(text[strategy_start:])
            parsed = {"strategy": strategy_only}
        strategy = parsed.get("strategy") if isinstance(parsed.get("strategy"), dict) else parsed
        dsl = parsed if isinstance(parsed.get("strategy"), dict) else {"strategy": strategy}
        market = strategy.setdefault("market", {})
        market.update({"exchange": "cn_stock", "instrument": market.get("instrument", "510300.SH"), "timeframe": market.get("timeframe", "1d")})
        for indicator in strategy.setdefault("indicators", []):
            params = indicator.setdefault("params", {})
            if isinstance(params.get("period"), str):
                params["period"] = int(float(params["period"]))
        for name in ("entry", "exit"):
            section = strategy.setdefault(name, {"long": None, "short": None})
            section["short"] = None
            for key in list(section):
                if key not in ("long", "short"):
                    section.pop(key, None)
        strategy["constraints"] = {"t_plus_one": True, "price_limit": 0.1, "allow_short": False, "lot_size": 100}
        risk = strategy.setdefault("risk", {})
        risk["stop_loss"] = -abs(float(risk.get("stop_loss", -0.05)))
        risk["max_position_pct"] = min(0.3, float(risk.get("max_position_pct", 0.3)))
        risk["max_drawdown"] = -abs(float(risk.get("max_drawdown", -0.15)))
        return {"dsl_json": json.dumps(dsl, ensure_ascii=False), "is_valid": "true", "strategy_name": str(strategy.get("name", "")), "error": ""}
    except Exception as exc:
        return {"dsl_json": "{}", "is_valid": "false", "strategy_name": "", "error": str(exc)}
$code$::text)) ELSE node END)
  FROM jsonb_array_elements(w.graph::jsonb->'nodes') AS node
))::text, updated_at = NOW()
WHERE w.app_id = '528cb3cb-4548-419d-8296-a68e857e83fe' AND w.version = 'draft';

UPDATE workflows published
SET graph = draft.graph, updated_at = NOW()
FROM apps app, workflows draft
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id AND draft.version = 'draft'
  AND published.id = app.workflow_id;
COMMIT;
