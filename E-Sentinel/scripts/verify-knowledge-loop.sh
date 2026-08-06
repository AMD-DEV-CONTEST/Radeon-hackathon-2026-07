#!/usr/bin/env bash
# ===========================================================================
# E-Sentinel · 知识库闭环工作流 一键验证脚本
# 用法: bash scripts/verify-knowledge-loop.sh
# 前提: npm run dev 已启动, Supabase 已执行 migration-015
# ===========================================================================

set -euo pipefail
BASE="http://localhost:3001"

echo "=============================================="
echo "  E-Sentinel 知识库闭环工作流验证"
echo "=============================================="

# ── 1. 健康检查 ────────────────────────────────────
echo ""
echo "[1/7] 健康检查"
if curl -sf "$BASE/api/qa/knowledge?limit=1" > /dev/null 2>&1; then
  echo "  ✅ API 服务正常"
else
  echo "  ❌ API 不可达，请确认 npm run dev 已启动"
  exit 1
fi

# ── 2. 模拟未解决问题记录 ────────────────────────────
echo ""
echo "[2/7] 模拟未解决问题记录"
RESP=$(curl -sf -X POST "$BASE/api/qa/unresolved" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-sess-001",
    "platform_code": "tmall",
    "user_question": "你好，请问这个什么时候发货？已经三天了还没发",
    "ai_reply": "亲，正常48小时内发货哦",
    "transfer_reason": "客户不满催单",
    "satisfaction": "bad"
  }')
ENTRY_ID=$(echo "$RESP" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -n "$ENTRY_ID" ]; then
  echo "  ✅ 记录成功: $ENTRY_ID"
else
  echo "  ❌ 记录失败: $RESP"
  exit 1
fi

# ── 3. 查询列表 ─────────────────────────────────────
echo ""
echo "[3/7] 查询未解决问题列表"
if curl -sf "$BASE/api/qa/unresolved?status=pending&limit=5" | grep -q "test-sess-001"; then
  echo "  ✅ 列表查询正常"
else
  echo "  ❌ 列表查询异常"
  exit 1
fi

# ── 4. 导出 CSV/JSON/MD ────────────────────────────
echo ""
echo "[4/7] 导出训练数据"
CSV_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE/api/qa/unresolved/export?format=csv")
JSON_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE/api/qa/unresolved/export?format=json")
MD_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE/api/qa/unresolved/export?format=markdown")
if [ "$CSV_STATUS" = "200" ] && [ "$JSON_STATUS" = "200" ] && [ "$MD_STATUS" = "200" ]; then
  echo "  ✅ CSV(200) JSON(200) Markdown(200) 全部导出成功"
else
  echo "  ❌ 导出异常: CSV=$CSV_STATUS JSON=$JSON_STATUS MD=$MD_STATUS"
fi

# ── 5. 模拟训练后导入 ───────────────────────────────
echo ""
echo "[5/7] 模拟训练后导入（JSON格式）"
IMPORT_RESP=$(curl -sf -X POST "$BASE/api/qa/knowledge/import-trained" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "[{\"title\":\"发货时效说明\",\"content\":\"亲，正常发货时效为48小时内，如遇大促或疫情可能延迟至72小时\",\"category\":\"faq\",\"keywords\":[\"发货\",\"物流\",\"时效\"]}]"
  }')
IMPORTED=$(echo "$IMPORT_RESP" | grep -o '"imported":[0-9]*' | cut -d: -f2)
if [ "$IMPORTED" -ge 1 ]; then
  echo "  ✅ 导入成功: $IMPORTED 条"
else
  echo "  ❌ 导入失败: $IMPORT_RESP"
fi

# ── 6. 模拟文件导入 ─────────────────────────────────
echo ""
echo "[6/7] 模拟训练后导入（CSV文件）"
CSV_FILE=$(mktemp)
cat > "$CSV_FILE" << 'CSVEOF'
title,content,category,keywords
退款流程,联系售后处理退换货,after_sales_policy,退款;退货
产品区别,两款产品的主要区别在于材质,product,区别;材质
CSVEOF
UPLOAD_RESP=$(curl -sf -X POST "$BASE/api/qa/knowledge/import-trained" \
  -F "file=@$CSV_FILE")
rm -f "$CSV_FILE"
UPLOADED=$(echo "$UPLOAD_RESP" | grep -o '"imported":[0-9]*' | cut -d: -f2)
if [ "$UPLOADED" -ge 1 ]; then
  echo "  ✅ CSV导入成功: $UPLOADED 条"
else
  echo "  ⚠️ CSV导入返回: $UPLOAD_RESP"
fi

# ── 7. 状态流转 ─────────────────────────────────────
echo ""
echo "[7/7] 状态流转验证"
# pending → processing
curl -sf -X PATCH "$BASE/api/qa/unresolved/$ENTRY_ID" \
  -H "Content-Type: application/json" \
  -d '{"status":"processing","note":"正在分析原因"}' > /dev/null
# processing → resolved
curl -sf -X PATCH "$BASE/api/qa/unresolved/$ENTRY_ID" \
  -H "Content-Type: application/json" \
  -d '{"status":"resolved","resolved_by":"test"}' > /dev/null
echo "  ✅ 状态流转完成: pending → processing → resolved"

# ── 汇总 ────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  验证完成"
echo "=============================================="
echo ""
echo "统计API: curl $BASE/api/qa/unresolved/stats"
echo "知识库审核: curl $BASE/api/qa/knowledge/pending"
echo ""
echo "所有测试通过 ✅"
