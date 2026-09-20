BEGIN;

UPDATE workflows w
SET graph = jsonb_set(
  w.graph::jsonb,
  '{nodes}',
  (SELECT jsonb_agg(
    CASE WHEN n->>'id' = '1785411748531' THEN
      jsonb_set(
        jsonb_set(n, '{data,variables}', jsonb_build_array(
          jsonb_build_object('variable','arg1','value_type','string','value_selector',jsonb_build_array('agent_execution','text')),
          jsonb_build_object('variable','arg2','value_type','string','value_selector',jsonb_build_array('agent_risk','text'))
        )),
        '{data,code}', to_jsonb($code$
import json
import re

def parse_simple_strategy(text):
    """Fallback parser for the small YAML dialect emitted by the agents."""
    def get(key, default=''):
        m = re.search(r'(?mi)^\s*(?:strategy\s+)?' + re.escape(key) + r'\s*:\s*(.+?)\s*$', text)
        return m.group(1).strip().strip('"\'') if m else default
    def number(value, default):
        try: return int(value) if re.match(r'^-?\d+$', value) else float(value)
        except Exception: return default
    indicators = []
    chunks = re.split(r'(?mi)^\s*-\s+name:\s*', text)[1:]
    for chunk in chunks:
        name = chunk.splitlines()[0].strip().strip('"\'')
        typ = re.search(r'(?mi)^\s*type:\s*(\S+)', chunk)
        period = re.search(r'(?mi)^\s*period:\s*([\w.%-]+)', chunk)
        field = re.search(r'(?mi)^\s*field:\s*(\S+)', chunk)
        indicators.append({'name':name, 'type':typ.group(1) if typ else 'EMA', 'params':{'period':number(period.group(1),20) if period else 20, 'field':field.group(1) if field else 'close'}})
    if not indicators:
        indicators = [{'name':'ema_fast','type':'EMA','params':{'period':20,'field':'close'}},{'name':'ema_slow','type':'EMA','params':{'period':50,'field':'close'}}]
    instrument = get('instrument', '510300.SH')
    timeframe = get('timeframe', '1d')
    stop = number(get('stop_loss','-0.05'), -0.05)
    max_pos = number(get('max_position_pct','0.3'), 0.3)
    return {'strategy': {'name': get('name', 'CN_multi_agent_strategy'), 'market': {'exchange':'cn_stock','instrument':instrument,'timeframe':timeframe}, 'indicators':indicators, 'entry': {'long':'ema_fast > ema_slow','short':None}, 'exit': {'long':'ema_fast < ema_slow','short':None}, 'risk': {'stop_loss':stop,'max_position_pct':max_pos,'max_drawdown':-0.15}}}

def parse_value(text):
    text = (text or '').strip()
    start, end = text.find('{'), text.rfind('}')
    candidate = text[start:end + 1] if start >= 0 and end > start else text
    try:
        return json.loads(candidate)
    except Exception:
        try:
            import yaml
            return yaml.safe_load(candidate)
        except Exception:
            return parse_simple_strategy(candidate)

def main(arg1: str, arg2: str = ''):
    dsl = parse_value(arg1)
    if not isinstance(dsl, dict):
        return {'dsl_json':'{}','is_valid':'false','strategy_name':'','error':'无法解析执行 Agent 输出'}
    if 'strategy' not in dsl:
        dsl = {'strategy': dsl}

    risk = parse_value(arg2) or {}
    risk_text = (arg2 or '').upper()
    decision = str(risk.get('risk_decision','')).upper() if isinstance(risk, dict) else ''
    if decision not in ('PASS','REVIEW','REJECT'):
        decision = 'REJECT' if 'REJECT' in risk_text else 'REVIEW'
    dsl['agent_risk_decision'] = decision
    if isinstance(risk, dict) and risk.get('risk_reasons'):
        dsl['risk_reasons'] = risk['risk_reasons']

    strategy = dsl['strategy']
    market = strategy.setdefault('market', {})
    market['exchange'] = 'cn_stock'
    if not (str(market.get('instrument','')).endswith('.SH') or str(market.get('instrument','')).endswith('.SZ')):
        market['instrument'] = '510300.SH'
    market.setdefault('timeframe','1d')
    for indicator in strategy.setdefault('indicators', []):
        params = indicator.setdefault('params', {})
        for key in ('period','fast_period','slow_period','signal_period'):
            if key in params:
                params[key] = int(float(params[key]))
        for key in ('std_dev','multiplier'):
            if key in params:
                params[key] = float(params[key])
    for name in ('entry','exit'):
        strategy.setdefault(name, {})['short'] = None
    risk_cfg = strategy.setdefault('risk', {})
    risk_cfg['stop_loss'] = -abs(float(risk_cfg.get('stop_loss',-0.05)))
    risk_cfg['max_position_pct'] = min(float(risk_cfg.get('max_position_pct',0.3)),0.3)
    risk_cfg['max_drawdown'] = -abs(float(risk_cfg.get('max_drawdown',-0.15)))
    strategy['constraints'] = {'t_plus_one':True,'price_limit':0.1,'allow_short':False,'lot_size':100}
    return {'dsl_json':json.dumps(dsl,ensure_ascii=False),'is_valid':'true','strategy_name':str(strategy.get('name','')),'error':''}
$code$::text))
    ELSE n END
  ) FROM jsonb_array_elements(w.graph::jsonb->'nodes') n)
)
WHERE w.id = (SELECT workflow_id FROM apps WHERE id='528cb3cb-4548-419d-8296-a68e857e83fe');

UPDATE workflows draft
SET graph=published.graph, updated_at=NOW()
FROM apps app, workflows published
WHERE app.id='528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.id='d5641408-df96-478b-a58e-6142837d7957'
  AND published.id=app.workflow_id;

COMMIT;
