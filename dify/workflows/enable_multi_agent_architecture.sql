BEGIN;

-- Turn the verified domestic workflow into a visible hierarchical multi-agent
-- graph.  All agents use the same AMD-served model, but each has a separate
-- role, prompt, trace entry, and output contract.
WITH current AS (
  SELECT w.id, w.graph::jsonb AS graph,
         (SELECT n FROM jsonb_array_elements(w.graph::jsonb->'nodes') n
          WHERE n->>'id' = 'llm') AS template
  FROM workflows w
  WHERE w.id = (SELECT workflow_id FROM apps
                WHERE id = '528cb3cb-4548-419d-8296-a68e857e83fe')
), configured AS (
  SELECT id,
    jsonb_agg(CASE WHEN n->>'id' = 'llm' THEN
      jsonb_set(jsonb_set(jsonb_set(n, '{data,title}', to_jsonb('资产配置 Agent'::text)),
        '{data,desc}', to_jsonb('顶层 Agent：理解用户目标，决定资产、周期、仓位和策略组合。'::text)),
        '{data,prompt_template}', to_jsonb(jsonb_build_array(
          jsonb_build_object('id','asset-system','role','system','text',$asset_system$
你是资产配置 Agent，运行在 AMD ROCm GPU 上。
你的职责是：从用户需求中提取国内证券市场标的、周期、风险预算和目标，规划趋势、套利、反转三类策略的组合权重。
禁止数字货币、境外交易所、合约和永续内容。只输出 JSON，不输出解释。
输出格式：{"agent":"asset_allocation","instrument":"510300.SH","timeframe":"1d","weights":{"trend":0.5,"arbitrage":0.2,"reversal":0.3},"risk_budget":0.3,"constraints":{"allow_short":false,"lot_size":100,"t_plus_one":true}}
用户需求：{{#sys.query#}}
国内知识约束：{{#1785415267075.body#}}
$asset_system$::text),
          jsonb_build_object('id','asset-user','role','user','text','请完成资产配置规划。'))))
    ELSE n END) AS nodes,
    (SELECT graph->'edges' FROM current) AS old_edges,
    (SELECT template FROM current) AS template
  FROM current, jsonb_array_elements(graph->'nodes') n
  GROUP BY id
), added AS (
  SELECT id, nodes || jsonb_build_array(
    jsonb_set(jsonb_set(jsonb_set(jsonb_set(template, '{id}', to_jsonb('agent_trend'::text)), '{data,title}', to_jsonb('策略 Agent A · 趋势'::text)), '{data,desc}', to_jsonb('中层策略 Agent：趋势跟随与均线突破。'::text)), '{position}', jsonb_build_object('x',220,'y',-210)),
    jsonb_set(jsonb_set(jsonb_set(jsonb_set(template, '{id}', to_jsonb('agent_arbitrage'::text)), '{data,title}', to_jsonb('策略 Agent B · 套利'::text)), '{data,desc}', to_jsonb('中层策略 Agent：价差、相关性和均值回归套利。'::text)), '{position}', jsonb_build_object('x',220,'y',-20)),
    jsonb_set(jsonb_set(jsonb_set(jsonb_set(template, '{id}', to_jsonb('agent_reversal'::text)), '{data,title}', to_jsonb('策略 Agent C · 反转'::text)), '{data,desc}', to_jsonb('中层策略 Agent：超跌反转与波动率修复。'::text)), '{position}', jsonb_build_object('x',220,'y',170)),
    jsonb_set(jsonb_set(jsonb_set(jsonb_set(template, '{id}', to_jsonb('agent_risk'::text)), '{data,title}', to_jsonb('全局风控 Agent · 独立否决'::text)), '{data,desc}', to_jsonb('底层独立 Agent：检查三路策略和资产配置，拥有最终否决权。'::text)), '{position}', jsonb_build_object('x',520,'y',-20)),
    jsonb_set(jsonb_set(jsonb_set(jsonb_set(template, '{id}', to_jsonb('agent_execution'::text)), '{data,title}', to_jsonb('执行 Agent · DSL 编排'::text)), '{data,desc}', to_jsonb('底层执行 Agent：根据风控结论生成可校验的国内策略 DSL。'::text)), '{position}', jsonb_build_object('x',820,'y',-20))
  ) AS nodes
  FROM configured
), prompts AS (
  SELECT id,
    (SELECT jsonb_agg(CASE
      WHEN n->>'id' = 'agent_trend' THEN jsonb_set(n, '{data,prompt_template}', to_jsonb(jsonb_build_array(jsonb_build_object('id','trend-system','role','system','text',$trend_system$
你是策略 Agent A（趋势）。只输出 JSON，不输出解释。根据用户需求和资产配置，提出国内市场趋势策略候选：EMA/MA/ADX/突破、入场退出、风险和失败条件。禁止做空。
用户需求：{{#sys.query#}}
资产配置 Agent：{{#llm.text#}}
$trend_system$::text),jsonb_build_object('id','trend-user','role','user','text','请生成趋势策略候选。'))))
      WHEN n->>'id' = 'agent_arbitrage' THEN jsonb_set(n, '{data,prompt_template}', to_jsonb(jsonb_build_array(jsonb_build_object('id','arb-system','role','system','text',$arb_system$
你是策略 Agent B（套利）。只输出 JSON，不输出解释。根据用户需求和资产配置，提出国内证券市场可执行的价差/相关性套利候选；若无法满足现货约束，明确标记 unavailable，不得虚构数据，不得裸卖空。
用户需求：{{#sys.query#}}
资产配置 Agent：{{#llm.text#}}
$arb_system$::text),jsonb_build_object('id','arb-user','role','user','text','请生成套利策略候选。'))))
      WHEN n->>'id' = 'agent_reversal' THEN jsonb_set(n, '{data,prompt_template}', to_jsonb(jsonb_build_array(jsonb_build_object('id','rev-system','role','system','text',$rev_system$
你是策略 Agent C（反转）。只输出 JSON，不输出解释。根据用户需求和资产配置，提出 RSI/布林带/波动率反转候选，明确风险与失效条件，禁止做空。
用户需求：{{#sys.query#}}
资产配置 Agent：{{#llm.text#}}
$rev_system$::text),jsonb_build_object('id','rev-user','role','user','text','请生成反转策略候选。'))))
      WHEN n->>'id' = 'agent_risk' THEN jsonb_set(n, '{data,prompt_template}', to_jsonb(jsonb_build_array(jsonb_build_object('id','risk-system','role','system','text',$risk_system$
你是独立的全局风控 Agent，拥有否决权。审查资产配置和三个策略候选：标的是否合法、是否满足 T+1/100股/禁止裸卖空、仓位和止损是否合理、策略是否有可验证依据。只输出 JSON：{"agent":"global_risk","risk_decision":"PASS|REVIEW|REJECT","selected_strategy":"trend|arbitrage|reversal","risk_reasons":[],"execution_constraints":{"max_position_pct":0.3,"stop_loss":-0.05,"allow_short":false,"lot_size":100}}。高风险或违反硬约束必须 REJECT。
用户需求：{{#sys.query#}}
资产配置：{{#llm.text#}}
趋势候选：{{#agent_trend.text#}}
套利候选：{{#agent_arbitrage.text#}}
反转候选：{{#agent_reversal.text#}}
$risk_system$::text),jsonb_build_object('id','risk-user','role','user','text','执行独立风控审查。'))))
      WHEN n->>'id' = 'agent_execution' THEN jsonb_set(n, '{data,prompt_template}', to_jsonb(jsonb_build_array(jsonb_build_object('id','exec-system','role','system','text',$exec_system$
你是执行 Agent。你不能绕过全局风控 Agent；当 risk_decision=REJECT 时，必须原样输出该否决结果，不得生成可执行策略。若为 PASS 或 REVIEW，则将选中的候选转换成严格合法的国内市场 JSON DSL，并在顶层保留 agent_risk_decision 和 risk_reasons。
只支持 cn_stock、.SH/.SZ、日线或分钟线现货；constraints 必须包含 t_plus_one=true、allow_short=false、lot_size=100；risk.stop_loss 必须为负数。只输出 JSON。
用户需求：{{#sys.query#}}
风控结论：{{#agent_risk.text#}}
趋势候选：{{#agent_trend.text#}}
套利候选：{{#agent_arbitrage.text#}}
反转候选：{{#agent_reversal.text#}}
$exec_system$::text),jsonb_build_object('id','exec-user','role','user','text','生成最终可校验执行计划。'))))
      ELSE n END) FROM jsonb_array_elements(nodes) n) AS nodes
  FROM added
), final_graph AS (
  SELECT id, jsonb_build_object(
    'nodes', (SELECT jsonb_agg(
      CASE WHEN n->>'id'='1785411748531' THEN
        jsonb_set(n, '{data,variables,0,value_selector}', jsonb_build_array('agent_execution','text'))
      ELSE n END) FROM jsonb_array_elements(nodes) n),
    'edges', jsonb_build_array(
      jsonb_build_object('id','1776072202913-source-1785415267075-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','start','targetType','http-request','iteration_id',NULL,'isInIteration',false),'type','custom','source','1776072202913','target','1785415267075','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','1785415267075-source-llm-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','http-request','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','1785415267075','target','llm','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','llm-source-agent_trend-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','llm','target','agent_trend','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','llm-source-agent_arbitrage-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','llm','target','agent_arbitrage','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','llm-source-agent_reversal-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','llm','target','agent_reversal','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','agent_trend-source-agent_risk-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','agent_trend','target','agent_risk','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','agent_arbitrage-source-agent_risk-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','agent_arbitrage','target','agent_risk','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','agent_reversal-source-agent_risk-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','agent_reversal','target','agent_risk','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','agent_risk-source-agent_execution-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','llm','iteration_id',NULL,'isInIteration',false),'type','custom','source','agent_risk','target','agent_execution','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','agent_execution-source-1785411748531-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','llm','targetType','code','iteration_id',NULL,'isInIteration',false),'type','custom','source','agent_execution','target','1785411748531','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','1785411748531-source-1785413034874-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','code','targetType','http-request','iteration_id',NULL,'isInIteration',false),'type','custom','source','1785411748531','target','1785413034874','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target'),
      jsonb_build_object('id','1785413034874-source-1785412277261-target','data',jsonb_build_object('loop_id',NULL,'isInLoop',false,'sourceType','http-request','targetType','answer','iteration_id',NULL,'isInIteration',false),'type','custom','source','1785413034874','target','1785412277261','zIndex',0,'selected',false,'sourceHandle','source','targetHandle','target')
    ),
    'viewport', jsonb_build_object('x',0,'y',0,'zoom',0.55)
  ) AS graph
  FROM prompts
)
UPDATE workflows w SET graph = final_graph.graph::text, updated_at = NOW()
FROM final_graph WHERE w.id = final_graph.id;

UPDATE workflows draft
SET graph = published.graph, updated_at = NOW()
FROM apps app, workflows published
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id
  AND draft.version = 'draft'
  AND published.id = app.workflow_id;

COMMIT;
