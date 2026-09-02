-- ============================================================
-- Migration: P0 — 数据库架构泛化（Channel-Agnostic）
-- 日期: 2025-07-01
-- 说明: 新增 source_channel / channel_message_id，
--       使 tasks 表不再绑定飞书单一通道，为微信等扩展铺路。
-- ============================================================

-- 1. 新增中立通道字段
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_channel TEXT DEFAULT 'WEB_APP';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS channel_message_id TEXT;

-- 2. 回填历史数据：已有 feishu_message_id 的记录 → 标记为 FEISHU 通道
UPDATE tasks 
SET source_channel = 'FEISHU', 
    channel_message_id = feishu_message_id 
WHERE feishu_message_id IS NOT NULL 
  AND channel_message_id IS NULL;

-- 3. 联合唯一索引（部分索引，NULL 天然不冲突）
--    防止同一通道的同一条消息被重复入库
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_channel_msg 
ON tasks(source_channel, channel_message_id) 
WHERE channel_message_id IS NOT NULL;

-- 4. 通道筛选索引
CREATE INDEX IF NOT EXISTS idx_tasks_source_channel ON tasks(source_channel);
