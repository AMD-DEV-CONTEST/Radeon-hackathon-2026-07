BEGIN;

-- Make the existing, verified workflow visibly express the five Agent
-- capabilities without changing its executable backtest path.
UPDATE workflows w
SET graph = jsonb_set(
  w.graph::jsonb,
  '{nodes}',
  (SELECT jsonb_agg(
    CASE WHEN node->>'id' = 'llm' THEN
      jsonb_set(
        jsonb_set(
          jsonb_set(
            jsonb_set(node, '{data,title}', to_jsonb('策略规划与推理'::text)),
            '{data,desc}', to_jsonb('在 AMD ROCm GPU 上完成任务规划、策略推理，并读取对话记忆。'::text)
          ),
          '{data,memory}', jsonb_build_object(
            'window', jsonb_build_object('size', 10, 'enabled', true),
            'role_prefix', jsonb_build_object('user', '', 'assistant', ''),
            'query_prompt_template', '{{#sys.query#}}\n\n{{#sys.files#}}'
          )
        ),
        '{data,prompt_template,0,text}', to_jsonb($prompt$
你是运行在 AMD ROCm GPU 上的中国境内证券市场量化投资助理，服务模型为 models/qwen-trader-merged。

你的工作方式：
1. 先理解用户目标，形成简洁的任务计划：需求解析 → 知识约束 → 策略生成 → DSL 校验 → 回测与风控。
2. 结合对话记忆和下面的 RAG 结果，保持用户偏好与上下文连续。
3. 只允许 A 股、境内场内 ETF 和指数；禁止数字货币、境外交易所、合约和永续内容。
4. 只输出最终合法 JSON，不输出思维过程、Markdown 或解释文字；规划由工作流运行记录体现。

国内证券市场 RAG 风控知识：
{{#1785415267075.body#}}

JSON 规则：
- 顶层只能包含 strategy。
- market 必须包含 exchange="cn_stock"、instrument、timeframe；代码使用 510300.SH 或 159915.SZ 格式。
- indicators 必须为数组，period 必须是整数。
- entry.short 和 exit.short 必须为 null。
- constraints 必须包含 t_plus_one=true、price_limit=0.1、allow_short=false、lot_size=100。
- risk 必须包含负数 stop_loss、max_position_pct 和负数 max_drawdown。
- 用户未指定时使用 instrument="510300.SH"、timeframe="1d"、stop_loss=-0.05、max_position_pct=0.3、max_drawdown=-0.15。

输出结构示例：
{"strategy":{"name":"CN_EMA_20_50","market":{"exchange":"cn_stock","instrument":"510300.SH","timeframe":"1d"},"indicators":[{"name":"ema_fast","type":"EMA","params":{"period":20,"field":"close"}},{"name":"ema_slow","type":"EMA","params":{"period":50,"field":"close"}}],"entry":{"long":"ema_fast > ema_slow","short":null},"exit":{"long":"ema_fast < ema_slow","short":null},"constraints":{"t_plus_one":true,"price_limit":0.1,"allow_short":false,"lot_size":100},"risk":{"stop_loss":-0.05,"max_position_pct":0.3,"max_drawdown":-0.15}}}
$prompt$::text)
      )
    ELSE node END
  ) FROM jsonb_array_elements(w.graph::jsonb->'nodes') AS node
  )
)
WHERE w.id = (SELECT workflow_id FROM apps WHERE id = '528cb3cb-4548-419d-8296-a68e857e83fe');

-- Keep the editable draft identical to the published workflow.
UPDATE workflows draft
SET graph = published.graph, updated_at = NOW()
FROM apps app, workflows published
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id
  AND draft.version = 'draft'
  AND published.id = app.workflow_id;

UPDATE workflows
SET updated_at = NOW()
WHERE id = (SELECT workflow_id FROM apps WHERE id = '528cb3cb-4548-419d-8296-a68e857e83fe');

COMMIT;
