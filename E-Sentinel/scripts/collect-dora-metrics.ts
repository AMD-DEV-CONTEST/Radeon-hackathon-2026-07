#!/usr/bin/env node
/**
 * DORA Metrics Collector
 * Sprint 8: 自动采集软件交付指标
 *
 * 用法:
 *   node scripts/collect-dora-metrics.ts [--period daily|weekly] [--env production]
 *
 * 指标:
 *   - Change Lead Time: 从 commit 到 production 的时间
 *   - Deployment Frequency: 部署频率
 *   - Change Fail Rate: 变更失败率
 *   - Recovery Time: 恢复时间 (MTTR)
 */

import { execSync } from "node:child_process";
import { createClient } from "@supabase/supabase-js";

// 配置
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
const TENANT_ID = process.env.DORA_TENANT_ID || "system";
const APP_NAME = process.env.npm_package_name || "qa-system";

interface GitCommit {
  hash: string;
  authorDate: string;
  committerDate: string;
  message: string;
}

interface DeploymentRecord {
  commitSha: string;
  deployedAt: string;
  success: boolean;
  rollbackTriggered: boolean;
}

interface DORAMetrics {
  recording_period: string;
  change_lead_time_avg_hours: number | null;
  change_lead_time_p50_hours: number | null;
  change_lead_time_p95_hours: number | null;
  deployment_count: number;
  deployment_frequency_per_day: number;
  failed_deployments: number;
  total_deployments: number;
  change_fail_rate: number;
  recovery_time_avg_minutes: number | null;
  recovery_time_p50_minutes: number | null;
  recovery_time_p95_minutes: number | null;
  rework_deployments: number;
  rework_rate: number;
}

// 获取 Git 提交历史
function getGitCommits(since: string): GitCommit[] {
  try {
    const output = execSync(
      `git log --since="${since}" --format="%H|%ai|%ci|%s" --no-merges`,
      { encoding: "utf-8", maxBuffer: 10 * 1024 * 1024 }
    );

    return output
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => {
        const [hash, authorDate, committerDate, ...msgParts] = line.split("|");
        return {
          hash,
          authorDate,
          committerDate,
          message: msgParts.join("|"),
        };
      });
  } catch {
    console.warn("[DORA] Could not get git history");
    return [];
  }
}

// 获取最近 N 天的部署记录 (从数据库或部署日志)
async function getDeploymentRecords(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  since: Date
): Promise<DeploymentRecord[]> {
  try {
    const { data, error } = await supabase
      .from("release_evidences")
      .select("commit_sha, created_at, status, rollback_triggered")
      .gte("created_at", since.toISOString())
      .in("status", ["completed", "rolled_back"]);

    if (error) {
      console.warn("[DORA] Could not fetch deployment records:", error.message);
      return [];
    }

    if (!data || !Array.isArray(data)) {
      return [];
    }

    return data.map((row: {
      commit_sha: string;
      created_at: string;
      status: string;
      rollback_triggered: boolean;
    }) => ({
      commitSha: row.commit_sha,
      deployedAt: row.created_at,
      success: row.status === "completed",
      rollbackTriggered: row.rollback_triggered,
    }));
  } catch {
    return [];
  }
}

// 计算 Lead Time (commit -> deployed)
function calculateLeadTime(
  commits: GitCommit[],
  deployments: DeploymentRecord[]
): { avg: number | null; p50: number | null; p95: number | null } {
  const leadTimes: number[] = [];

  for (const deployment of deployments) {
    const commit = commits.find((c) => c.hash.startsWith(deployment.commitSha));
    if (!commit) continue;

    const commitTime = new Date(commit.authorDate).getTime();
    const deployTime = new Date(deployment.deployedAt).getTime();

    if (deployTime > commitTime) {
      leadTimes.push((deployTime - commitTime) / (1000 * 60 * 60)); // hours
    }
  }

  if (leadTimes.length === 0) {
    return { avg: null, p50: null, p95: null };
  }

  leadTimes.sort((a, b) => a - b);

  const avg = leadTimes.reduce((a, b) => a + b, 0) / leadTimes.length;
  const p50 = leadTimes[Math.floor(leadTimes.length * 0.5)];
  const p95 = leadTimes[Math.floor(leadTimes.length * 0.95)];

  return { avg, p50, p95 };
}

// 计算 Recovery Time (从 rollback 触发到恢复)
async function calculateRecoveryTime(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  since: Date
): Promise<{ avg: number | null; p50: number | null; p95: number | null }> {
  try {
    const { data, error } = await supabase
      .from("release_evidences")
      .select("rollback_triggered_at, rollback_executed_at")
      .gte("created_at", since.toISOString())
      .eq("rollback_triggered", true)
      .not("rollback_executed_at", "is", null);

    if (error || !data || !Array.isArray(data) || data.length === 0) {
      return { avg: null, p50: null, p95: null };
    }

    const recoveryTimes = data
      .filter((row: {
        rollback_triggered_at: string | null;
        rollback_executed_at: string | null;
      }) => row.rollback_triggered_at && row.rollback_executed_at)
      .map((row: {
        rollback_triggered_at: string;
        rollback_executed_at: string;
      }) => {
        const triggerTime = new Date(row.rollback_triggered_at).getTime();
        const execTime = new Date(row.rollback_executed_at).getTime();
        return (execTime - triggerTime) / (1000 * 60); // minutes
      });

    if (recoveryTimes.length === 0) {
      return { avg: null, p50: null, p95: null };
    }

    recoveryTimes.sort((a: number, b: number) => a - b);

    const avg = recoveryTimes.reduce((a: number, b: number) => a + b, 0) / recoveryTimes.length;
    const p50 = recoveryTimes[Math.floor(recoveryTimes.length * 0.5)];
    const p95 = recoveryTimes[Math.floor(recoveryTimes.length * 0.95)];

    return { avg, p50, p95 };
  } catch {
    return { avg: null, p50: null, p95: null };
  }
}

// 主函数
async function main() {
  const period = process.argv.includes("--weekly") ? "weekly" : "daily";
  const environment = process.argv.includes("--staging") ? "staging" : "production";

  console.log(`[DORA] Collecting metrics for ${period} period, env: ${environment}`);

  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
    console.error("[DORA] Missing Supabase configuration");
    process.exit(1);
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  // 计算时间范围
  const now = new Date();
  const since = new Date(now);
  since.setDate(since.getDate() - (period === "weekly" ? 7 : 1));

  // 获取数据
  const commits = getGitCommits(since.toISOString());
  const deployments = await getDeploymentRecords(supabase, since);

  console.log(`[DORA] Found ${commits.length} commits, ${deployments.length} deployments`);

  // 计算指标
  const leadTime = calculateLeadTime(commits, deployments);
  const recoveryTime = await calculateRecoveryTime(supabase, since);

  const totalDeployments = deployments.length;
  const failedDeployments = deployments.filter((d) => !d.success || d.rollbackTriggered).length;
  const reworkDeployments = deployments.filter((d) => d.rollbackTriggered).length;

  const metrics: Omit<DORAMetrics, 'recording_period'> = {
    change_lead_time_avg_hours: leadTime.avg ? Math.round(leadTime.avg * 100) / 100 : null,
    change_lead_time_p50_hours: leadTime.p50 ? Math.round(leadTime.p50 * 100) / 100 : null,
    change_lead_time_p95_hours: leadTime.p95 ? Math.round(leadTime.p95 * 100) / 100 : null,
    deployment_count: totalDeployments,
    deployment_frequency_per_day: totalDeployments / (period === "weekly" ? 7 : 1),
    failed_deployments: failedDeployments,
    total_deployments: totalDeployments,
    change_fail_rate: totalDeployments > 0 ? Math.round((failedDeployments / totalDeployments) * 10000) / 10000 : 0,
    recovery_time_avg_minutes: recoveryTime.avg ? Math.round(recoveryTime.avg * 100) / 100 : null,
    recovery_time_p50_minutes: recoveryTime.p50 ? Math.round(recoveryTime.p50 * 100) / 100 : null,
    recovery_time_p95_minutes: recoveryTime.p95 ? Math.round(recoveryTime.p95 * 100) / 100 : null,
    rework_deployments: reworkDeployments,
    rework_rate: totalDeployments > 0 ? Math.round((reworkDeployments / totalDeployments) * 10000) / 10000 : 0,
  };

  // 保存到数据库
  const record = {
    tenant_id: TENANT_ID,
    recording_period: period,
    ...metrics,
    application_name: APP_NAME,
    environment: environment,
  };

  const { error } = await supabase.from("dora_metrics").insert(record);

  if (error) {
    console.error("[DORA] Failed to save metrics:", error.message);
    process.exit(1);
  }

  console.log("[DORA] Metrics collected successfully:");
  console.log(`  - Lead Time: avg ${metrics.change_lead_time_avg_hours ?? "N/A"}h, p50 ${metrics.change_lead_time_p50_hours ?? "N/A"}h`);
  console.log(`  - Deployments: ${metrics.deployment_count} (${metrics.deployment_frequency_per_day.toFixed(2)}/day)`);
  console.log(`  - Fail Rate: ${(metrics.change_fail_rate * 100).toFixed(1)}%`);
  console.log(`  - Recovery Time: avg ${metrics.recovery_time_avg_minutes ?? "N/A"}min`);
}

main().catch((err) => {
  console.error("[DORA] Error:", err);
  process.exit(1);
});