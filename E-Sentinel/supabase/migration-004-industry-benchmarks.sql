-- Migration 004: Create industry_benchmarks table with seed data
-- Run this in Supabase SQL Editor if the table doesn't exist yet

-- Create table
CREATE TABLE IF NOT EXISTS public.industry_benchmarks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_name TEXT NOT NULL,
  industry_avg NUMERIC(5,2) NOT NULL,
  industry_top NUMERIC(5,2),
  category TEXT,
  period TEXT DEFAULT '2025Q4',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Enable RLS
ALTER TABLE public.industry_benchmarks ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read
CREATE POLICY "Allow read for authenticated" ON public.industry_benchmarks
  FOR SELECT USING (auth.role() = 'authenticated');

-- Allow service_role to insert/update
CREATE POLICY "Allow insert for service_role" ON public.industry_benchmarks
  FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow update for service_role" ON public.industry_benchmarks
  FOR UPDATE USING (true);

-- Seed data: industry benchmarks for e-commerce customer service robots
INSERT INTO public.industry_benchmarks (metric_name, industry_avg, industry_top, category, period) VALUES
  ('独立接待率', 65.0, 85.0, '接待效率', '2025Q4'),
  ('首次响应时间(秒)', 12.0, 3.0, '接待效率', '2025Q4'),
  ('平均响应时间(秒)', 45.0, 15.0, '接待效率', '2025Q4'),
  ('好评率', 82.0, 95.0, '满意度', '2025Q4'),
  ('差评率', 8.0, 2.0, '满意度', '2025Q4'),
  ('询单转化率', 28.0, 45.0, '转化', '2025Q4'),
  ('流失率', 35.0, 15.0, '转化', '2025Q4'),
  ('知识库命中率', 70.0, 90.0, '知识库', '2025Q4'),
  ('话术覆盖率', 60.0, 88.0, '话术配置', '2025Q4'),
  ('问题解决率', 72.0, 92.0, '服务质量', '2025Q4'),
  ('转人工率', 25.0, 8.0, '接待效率', '2025Q4'),
  ('客户复购率', 22.0, 40.0, '转化', '2025Q4'),
  ('响应满意度', 78.0, 93.0, '满意度', '2025Q4'),
  ('退货退款处理时长(小时)', 48.0, 12.0, '售后效率', '2025Q4'),
  ('工单关闭率', 85.0, 98.0, '售后效率', '2025Q4')
ON CONFLICT (id) DO NOTHING;
