BEGIN;

UPDATE apps
SET name = 'AMD 国内市场量化智能体', updated_at = NOW()
WHERE id = '528cb3cb-4548-419d-8296-a68e857e83fe';

WITH current_draft AS (
  SELECT id, graph::jsonb AS graph
  FROM workflows
  WHERE app_id = '528cb3cb-4548-419d-8296-a68e857e83fe' AND version = 'draft'
), updated AS (
  SELECT id,
    jsonb_set(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(
              graph,
              '{nodes,6,data,url}',
              to_jsonb('http://host.docker.internal:8080/api/cn/backtest/report'::text)
            ),
            '{nodes,6,data,body,data,0,value}',
            to_jsonb('{{#1785411748531.dsl_json#}}'::text)
          ),
          '{nodes,8,data,prompt_template,0,text}',
          to_jsonb($prompt$你是运行在 AMD ROCm GPU 上的中国境内证券市场量化策略 DSL 模型，当前服务 ID 为 models/qwen-trader-merged。

以下内容来自国内证券市场 RAG 风控知识，仅作为约束参考：
{{#1785415267075.body#}}

任务：把用户需求转换为严格合法的 JSON。只支持 A股、境内场内ETF和指数；禁止生成数字货币、境外交易所、合约或永续内容。

输出规则：
1. 只输出 JSON，不要 Markdown 或解释，顶层只能包含 strategy。
2. market 必须包含 exchange="cn_stock"、instrument 和 timeframe；证券代码使用 510300.SH 或 159915.SZ 格式。
3. indicators 必须为数组；period 必须为整数。
4. entry.short 和 exit.short 必须为 null。
5. constraints 必须包含 t_plus_one=true、price_limit=0.1、allow_short=false、lot_size=100。
6. risk 必须包含负数 stop_loss、max_position_pct 和负数 max_drawdown。
7. 用户未指定时使用 instrument="510300.SH"、timeframe="1d"、stop_loss=-0.05、max_position_pct=0.3、max_drawdown=-0.15。

严格输出结构：
{"strategy":{"name":"CN_EMA_20_50","market":{"exchange":"cn_stock","instrument":"510300.SH","timeframe":"1d"},"indicators":[{"name":"ema_fast","type":"EMA","params":{"period":20,"field":"close"}},{"name":"ema_slow","type":"EMA","params":{"period":50,"field":"close"}}],"entry":{"long":"ema_fast > ema_slow","short":null},"exit":{"long":"ema_fast < ema_slow","short":null},"constraints":{"t_plus_one":true,"price_limit":0.1,"allow_short":false,"lot_size":100},"risk":{"stop_loss":-0.05,"max_position_pct":0.3,"max_drawdown":-0.15}}}$prompt$::text)
        ),
        '{nodes,8,data,prompt_template,1,text}',
        to_jsonb($user$请根据以下用户需求生成国内证券市场策略 DSL，只返回合法 JSON：

{{#sys.query#}}$user$::text)
      ),
      '{nodes,4,data,code}',
      to_jsonb($code$import json
import re

def main(arg1: str):
    try:
        text = (arg1 or "").strip()
        text = re.sub(r"^\s*assistant\s*$", "", text, flags=re.MULTILINE)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("No JSON object found")
        parsed = json.loads(text[start:end + 1])
        if "strategy" in parsed and isinstance(parsed["strategy"], dict):
            dsl, strategy = parsed, parsed["strategy"]
        else:
            strategy, dsl = parsed, {"strategy": parsed}

        market = strategy.setdefault("market", {})
        market["exchange"] = "cn_stock"
        market.setdefault("instrument", "510300.SH")
        market.setdefault("timeframe", "1d")
        for indicator in strategy.setdefault("indicators", []):
            params = indicator.setdefault("params", {})
            if isinstance(params.get("period"), str):
                params["period"] = int(float(params["period"]))

        for section_name in ("entry", "exit"):
            section = strategy.setdefault(section_name, {"long": None, "short": None})
            section["short"] = None
            for key in list(section):
                if key not in ("long", "short"):
                    section.pop(key, None)

        constraints = strategy.setdefault("constraints", {})
        constraints.update({"t_plus_one": True, "price_limit": 0.1, "allow_short": False, "lot_size": 100})
        risk = strategy.setdefault("risk", {})
        try:
            risk["stop_loss"] = -abs(float(risk.get("stop_loss", -0.05)))
        except (TypeError, ValueError):
            risk["stop_loss"] = -0.05
        risk["max_position_pct"] = min(0.3, float(risk.get("max_position_pct", 0.3)))
        risk["max_drawdown"] = -abs(float(risk.get("max_drawdown", -0.15)))

        result = json.dumps(dsl, ensure_ascii=False)
        return {"dsl_json": result, "is_valid": "true", "strategy_name": str(strategy.get("name", "")), "error": ""}
    except Exception as exc:
        return {"dsl_json": "{}", "is_valid": "false", "strategy_name": "", "error": str(exc)}
$code$::text)
    ) AS graph
  FROM current_draft
)
UPDATE workflows w
SET graph = updated.graph::text, updated_at = NOW()
FROM updated
WHERE w.id = updated.id;

-- Node positions change when canvas notes are removed; target the code node by id.
UPDATE workflows w
SET graph = jsonb_set(
  w.graph::jsonb,
  '{nodes}',
  (
    SELECT jsonb_agg(
      CASE WHEN node->>'id' = '1785411748531' THEN
        jsonb_set(node, '{data,code}', to_jsonb($fixcode$import json
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
$fixcode$::text))
      ELSE node END
    )
    FROM jsonb_array_elements(w.graph::jsonb->'nodes') AS node
  )
)::text,
updated_at = NOW()
WHERE w.app_id = '528cb3cb-4548-419d-8296-a68e857e83fe' AND w.version = 'draft';

-- Keep the currently published local demo aligned with the migrated draft.
UPDATE workflows published
SET graph = draft.graph, updated_at = NOW()
FROM apps app, workflows draft
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id
  AND draft.version = 'draft'
  AND published.id = app.workflow_id;

COMMIT;
