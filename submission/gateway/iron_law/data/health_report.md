# UAS 系统健康巡检报告

**巡检时间**: 2026-06-04T04:18:19 UTC

---

## 1. Orchestrator 服务
- **端点**: `http://127.0.0.1:8000/health`
- **状态**: ✅ ok
- **响应摘要**: `{"status":"ok","service":"orchestrator","time":"2026-06-04T04:18:19.691699Z"}`

## 2. Gateway 服务
- **端点**: `http://127.0.0.1:8001/health`
- **状态**: ✅ ok
- **响应摘要**: `{"status":"ok","service":"streaming_gateway","time":"2026-06-04T04:18:19.704079+00:00","launchers":["aws-hk","jd-ecs"],"agents_online":2,"agents":[{"agent_id":"5fd4b512-3d84-454b-9b7f-127d3ecce069","agent_name":"reasonix-aws-hk","agent_type":"reasonix","status":"online_idle"},{"agent_id":"de795bfe-db62-4824-884a-76ef17262237","agent_name":"scc-jd-ecs","agent_type":"claude_code","status":"online_idle"}],"cost_guard":{"claude_code":{"active":0,"max":null},"reasonix":{"active":0,"max":null}},"sessions":[]}`

## 3. RAG Service 服务
- **端点**: `http://127.0.0.1:8010/health`
- **状态**: ✅ ok
- **响应摘要**: `{"status":"ok","service":"rag_service","time":"2026-06-04T04:18:19.735084Z","embedding_model":"BAAI/bge-large-zh-v1.5","dimensions":1024,"total_cases":6}`

## 4. Boundary 巡检服务
- **端点**: `http://127.0.0.1:8020/health`
- **状态**: ✅ ok
- **响应摘要**: `{"status":"ok","service":"boundary","time":"2026-06-04T04:18:19.748322+00:00"}`

## 5. 铁律系统 (Iron Law)
- **端点**: `http://127.0.0.1:8000/iron-law/health`
- **状态**: ✅ ok
- **响应摘要**: `{"status":"ok","service":"iron-law","rag_service":"ok","boundary_service":"ok","time":"2026-06-04T04:18:19.782132+00:00"}`

---

## 结论：5/5 服务正常运行
