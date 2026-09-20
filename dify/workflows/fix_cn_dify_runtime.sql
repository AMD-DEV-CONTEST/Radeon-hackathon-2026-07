BEGIN;

-- Repair the two HTTP URLs and replace the code node after browser editing
-- accidentally appended the old values/code. Apply to draft and published.
UPDATE workflows w
SET graph = jsonb_build_object(
  'nodes', (SELECT jsonb_agg(
    CASE
      WHEN node->>'id' = '1785413034874' THEN
        jsonb_set(node, '{data,url}', to_jsonb('http://host.docker.internal:8080/api/cn/backtest/report'::text))
      WHEN node->>'id' = '1785415267075' THEN
        jsonb_set(node, '{data,url}', to_jsonb('http://host.docker.internal:8080/api/knowledge'::text))
      WHEN node->>'id' = '1785411748531' THEN
        jsonb_set(node, '{data,code}', to_jsonb($code$
import json
import re

def main(arg1: str):
    try:
        text = (arg1 or '').strip()
        text = re.sub(r'^\s*assistant\s*$', '', text, flags=re.IGNORECASE | re.MULTILINE).strip()
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise ValueError('未找到策略 JSON')
        dsl = json.loads(text[start:end + 1])
        # Qwen may emit either a canonical wrapper or `strategy = {...}`.
        # Normalize both forms before applying the domestic-market rules.
        if 'strategy' not in dsl:
            dsl = {'strategy': dsl}
        strategy = dsl['strategy']
        market = strategy.setdefault('market', {})
        market['exchange'] = 'cn_stock'
        if not (str(market.get('instrument', '')).endswith('.SH') or str(market.get('instrument', '')).endswith('.SZ')):
            market['instrument'] = '510300.SH'
        market.setdefault('timeframe', '1d')
        for indicator in strategy.setdefault('indicators', []):
            params = indicator.setdefault('params', {})
            for key in ('period', 'fast_period', 'slow_period', 'signal_period'):
                if key in params:
                    params[key] = int(float(params[key]))
            for key in ('std_dev', 'multiplier'):
                if key in params:
                    params[key] = float(params[key])
        for name in ('entry', 'exit'):
            section = strategy.setdefault(name, {})
            section['short'] = None
        risk = strategy.setdefault('risk', {})
        risk['stop_loss'] = -abs(float(risk.get('stop_loss', -0.05)))
        risk['max_position_pct'] = min(float(risk.get('max_position_pct', 0.3)), 0.3)
        risk['max_drawdown'] = -abs(float(risk.get('max_drawdown', -0.15)))
        strategy['constraints'] = {'t_plus_one': True, 'price_limit': 0.1, 'allow_short': False, 'lot_size': 100}
        return {'dsl_json': json.dumps(dsl, ensure_ascii=False), 'is_valid': 'true', 'strategy_name': str(strategy.get('name', '')), 'error': ''}
    except Exception as exc:
        return {'dsl_json': '{}', 'is_valid': 'false', 'strategy_name': '', 'error': str(exc)}
$code$::text))
      ELSE node
    END
  ) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.graph::jsonb) = 'object' THEN w.graph::jsonb->'nodes' ELSE w.graph::jsonb END) AS node),
  'edges', jsonb_build_array(
    jsonb_build_object('zIndex',0,'sourceHandle','source','id','1776072202913-source-1785415267075-target','target','1785415267075','data',jsonb_build_object('sourceType','start','isInLoop',false,'targetType','http-request','isInIteration',false,'loop_id',NULL,'iteration_id',NULL),'type','custom','source','1776072202913','selected',false,'targetHandle','target'),
    jsonb_build_object('zIndex',0,'sourceHandle','source','id','1785415267075-source-llm-target','target','llm','data',jsonb_build_object('sourceType','http-request','isInLoop',false,'targetType','llm','isInIteration',false,'loop_id',NULL,'iteration_id',NULL),'type','custom','source','1785415267075','selected',false,'targetHandle','target'),
    jsonb_build_object('zIndex',0,'sourceHandle','source','id','llm-source-1785411748531-target','target','1785411748531','data',jsonb_build_object('sourceType','llm','isInLoop',false,'targetType','code','isInIteration',false,'loop_id',NULL,'iteration_id',NULL),'type','custom','source','llm','selected',false,'targetHandle','target'),
    jsonb_build_object('zIndex',0,'sourceHandle','source','id','1785411748531-source-1785413034874-target','target','1785413034874','data',jsonb_build_object('sourceType','code','isInLoop',false,'targetType','http-request','isInIteration',false,'loop_id',NULL,'iteration_id',NULL),'type','custom','source','1785411748531','selected',false,'targetHandle','target'),
    jsonb_build_object('zIndex',0,'sourceHandle','source','id','1785413034874-source-1785412277261-target','target','1785412277261','data',jsonb_build_object('sourceType','http-request','isInLoop',false,'targetType','answer','isInIteration',false,'loop_id',NULL,'iteration_id',NULL),'type','custom','source','1785413034874','selected',false,'targetHandle','target')
  ),
  'viewport', jsonb_build_object('x',0,'y',0,'zoom',0.7)
)::text,
updated_at = NOW()
WHERE w.id = (
  SELECT workflow_id FROM apps
  WHERE id = '528cb3cb-4548-419d-8296-a68e857e83fe'
);

-- Dify published workflows use a timestamp version and are referenced by apps.workflow_id.
UPDATE workflows draft
SET graph = published.graph, updated_at = NOW()
FROM apps app, workflows published
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id
  AND draft.version = 'draft'
  AND published.id = app.workflow_id;

COMMIT;
