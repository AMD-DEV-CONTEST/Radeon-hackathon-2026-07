-- =====================================================================
-- add_intent_routing.sql — 给 "AMD 国内市场量化智能体" 工作流加意图路由
--
-- 效果：用户输入先过 /api/tools/intent 意图分类
--   ├─ strategy_generation → 走原有 NL→RAG→DSL→回测→风控 管道（主链路不变）
--   └─ 其他（计算/查询/闲聊） → 走 /api/tools/query 统一链路 + 通用回答
--
-- ⚠️ 前置条件（务必执行）：
--   1. 备份工作流：SELECT id, graph FROM workflows
--      WHERE app_id='528cb3cb-4548-419d-8296-a68e857e83fe' AND version='draft';
--   2. 确认 FastAPI :8080 已部署 external_tools（/api/tools/intent、/api/tools/query）
--   3. 本补丁按「节点类型动态定位」，不硬编码节点 id；Dify 版本若节点
--      schema 不同（如 code 节点 inputs 结构），优先用 UI 手动配置主方案
--      （见 add_intent_routing.md）
--
-- 用法：psql -U <dbuser> -d <difydb> -f add_intent_routing.sql
-- =====================================================================

BEGIN;

DO $$
DECLARE
    g jsonb;
    nodes jsonb;
    edges jsonb;
    start_id text;
    rag_id text;
    answer_id text;
    new_nodes jsonb;
    new_edges jsonb;
    app_id text := '528cb3cb-4548-419d-8296-a68e857e83fe';

    intent_id   text := '1785419999001';  -- HTTP: 意图分类
    intent_code text := '1785419999002';  -- code: 解析 intent
    ifelse_id   text := '1785419999003';  -- if-else: 路由
    query_id    text := '1785419999004';  -- HTTP: /api/tools/query
    general_llm text := '1785419999005';  -- LLM: 通用回答
BEGIN
    SELECT w.graph::jsonb INTO g
    FROM workflows w
    WHERE w.app_id = app_id AND w.version = 'draft'
    FOR UPDATE;

    IF g IS NULL THEN
        RAISE EXCEPTION 'workflow draft not found for app %', app_id;
    END IF;

    nodes := CASE WHEN jsonb_typeof(g) = 'object' THEN g->'nodes' ELSE g END;
    edges := CASE WHEN jsonb_typeof(g) = 'object' THEN g->'edges' ELSE '[]'::jsonb END;

    SELECT node->>'id' INTO start_id
    FROM jsonb_array_elements(nodes) node WHERE node->>'type' = 'start';
    SELECT node->>'id' INTO rag_id
    FROM jsonb_array_elements(nodes) node
    WHERE node->>'type' = 'http-request'
      AND node->'data'->>'url' LIKE '%/api/knowledge%';
    SELECT node->>'id' INTO answer_id
    FROM jsonb_array_elements(nodes) node WHERE node->>'type' = 'answer';

    IF start_id IS NULL OR rag_id IS NULL OR answer_id IS NULL THEN
        RAISE EXCEPTION 'cannot locate start/rag/answer (start=%, rag=%, answer=%)',
            start_id, rag_id, answer_id;
    END IF;

    -- 1. 追加 5 个新节点
    new_nodes := nodes || jsonb_build_array(
        jsonb_build_object(
            'id', intent_id, 'type', 'http-request',
            'position', jsonb_build_object('x', 60, 'y', 120),
            'data', jsonb_build_object(
                'method', 'get',
                'url', 'http://host.docker.internal:8080/api/tools/intent?text={{#sys.query#}}',
                'authorization', jsonb_build_object('type', 'no-auth'),
                'body', jsonb_build_object('type', 'none'),
                'timeout', jsonb_build_object('max_connect_timeout', 10, 'max_read_timeout', 60, 'max_write_timeout', 10),
                'variables', jsonb_build_array()
            )
        ),
        jsonb_build_object(
            'id', intent_code, 'type', 'code',
            'position', jsonb_build_object('x', 60, 'y', 200),
            'data', jsonb_build_object(
                'code', 'def main(body: str):\n    import json\n    try:\n        obj = json.loads(body or "{}")\n        intent = obj.get("intent", "general")\n    except Exception:\n        intent = "general"\n    return {"intent": intent}\n',
                'outputs', jsonb_build_object('intent', jsonb_build_object('type', 'string')),
                'variables', jsonb_build_array()
            )
        ),
        jsonb_build_object(
            'id', ifelse_id, 'type', 'if-else',
            'position', jsonb_build_object('x', 60, 'y', 280),
            'data', jsonb_build_object(
                'title', '意图路由',
                'conditions', jsonb_build_array(jsonb_build_object(
                    'variable_selector', jsonb_build_array(intent_code, 'intent'),
                    'comparison_operator', 'contains',
                    'value', 'strategy_generation'
                )),
                'logical_operator', 'and',
                'case_id', 'case-intent-routing'
            )
        ),
        jsonb_build_object(
            'id', query_id, 'type', 'http-request',
            'position', jsonb_build_object('x', 420, 'y', 280),
            'data', jsonb_build_object(
                'method', 'get',
                'url', 'http://host.docker.internal:8080/api/tools/query?text={{#sys.query#}}',
                'authorization', jsonb_build_object('type', 'no-auth'),
                'body', jsonb_build_object('type', 'none'),
                'timeout', jsonb_build_object('max_connect_timeout', 10, 'max_read_timeout', 60, 'max_write_timeout', 10),
                'variables', jsonb_build_array()
            )
        ),
        jsonb_build_object(
            'id', general_llm, 'type', 'llm',
            'position', jsonb_build_object('x', 420, 'y', 360),
            'data', jsonb_build_object(
                'model', jsonb_build_object('provider', 'openai_api_compatible', 'name', 'models/qwen-trader-merged', 'mode', 'chat'),
                'prompt_template', jsonb_build_array(
                    jsonb_build_object('role', 'system', 'text',
                        '你是运行在 AMD ROCm GPU 上的通用量化助理。基于下方「工具结果」回答用户问题。规则：1) 引用数据时必须注明来源、获取时间与置信度；2) 区分事实与推断；3) 合成/演示数据必须明确说明；4) 无法回答时说明边界并给方法建议。'),
                    jsonb_build_object('role', 'user', 'text',
                        '用户问题：{{#sys.query#}}\n\n工具结果：{{#' || query_id || '.body#}}')
                ),
                'variables', jsonb_build_array()
            )
        )
    );

    -- 2. 重写 edges：start 原边移除，接入意图路由链；DSL 主链其余边保留
    new_edges := (
        SELECT COALESCE(jsonb_agg(e), '[]'::jsonb)
        FROM jsonb_array_elements(edges) e
        WHERE e->>'source' <> start_id
    ) || jsonb_build_array(
        jsonb_build_object('id', start_id || '-source-' || intent_id || '-target', 'source', start_id,
            'target', intent_id, 'sourceHandle', 'source', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', intent_id || '-source-' || intent_code || '-target', 'source', intent_id,
            'target', intent_code, 'sourceHandle', 'source', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', intent_code || '-source-' || ifelse_id || '-target', 'source', intent_code,
            'target', ifelse_id, 'sourceHandle', 'source', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', ifelse_id || '-true-' || rag_id || '-target', 'source', ifelse_id,
            'target', rag_id, 'sourceHandle', 'true', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', ifelse_id || '-false-' || query_id || '-target', 'source', ifelse_id,
            'target', query_id, 'sourceHandle', 'false', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', query_id || '-source-' || general_llm || '-target', 'source', query_id,
            'target', general_llm, 'sourceHandle', 'source', 'targetHandle', 'target', 'type', 'custom'),
        jsonb_build_object('id', general_llm || '-source-' || answer_id || '-target', 'source', general_llm,
            'target', answer_id, 'sourceHandle', 'source', 'targetHandle', 'target', 'type', 'custom')
    );

    -- 3. 写回 draft
    UPDATE workflows w
    SET graph = jsonb_build_object('nodes', new_nodes, 'edges', new_edges)::text,
        updated_at = NOW()
    WHERE w.app_id = app_id AND w.version = 'draft';

    RAISE NOTICE 'intent routing applied: start=% rag=% answer=% nodes=% edges=%',
        start_id, rag_id, answer_id,
        jsonb_array_length(new_nodes), jsonb_array_length(new_edges);
END $$;

-- 同步到已发布版本
UPDATE workflows published
SET graph = draft.graph, updated_at = NOW()
FROM apps app, workflows draft
WHERE app.id = '528cb3cb-4548-419d-8296-a68e857e83fe'
  AND draft.app_id = app.id AND draft.version = 'draft'
  AND published.id = app.workflow_id;

COMMIT;
