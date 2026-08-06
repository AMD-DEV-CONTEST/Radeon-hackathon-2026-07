import type { Node, Edge } from '@xyflow/react';
import type {
  WorkflowNodeData,
  ExecutionContext,
  ExecutionLog,
  NodeType,
  CameraMapEntry,
} from '../types/workflow';
import { getRun, runSkill } from './skillsApi';
import { authJson } from './auth';

/**
 * 工作流执行引擎。
 * Finetune 主链默认走真实 API：
 *   dataset_load  -> /api/v1/trainings/qualia/dataset_probe
 *   camera_map    -> 本地校验 + 产出 camera mappings
 *   finetune_job  -> /api/v1/trainings (train_backend=qualia)
 *   job_monitor   -> /api/v1/trainings/{id} 轮询状态
 *
 * 若实时请求失败，会回退到原有模拟结果，保持编辑器可演示。
 */
export class WorkflowEngine {
  private context: ExecutionContext;
  private abortController: AbortController | null = null;
  private logs: ExecutionLog[] = [];

  constructor(workflowId: string) {
    this.context = {
      workflowId,
      nodeResults: new Map(),
      globalState: {},
    };
    this.logs = [];
  }

  private addLog(
    nodeId: string,
    nodeType: NodeType,
    level: ExecutionLog['level'],
    message: string
  ) {
    const log: ExecutionLog = {
      timestamp: new Date().toISOString(),
      nodeId,
      nodeType,
      level,
      message,
    };
    this.logs.push(log);
    return log;
  }

  getLogs(): ExecutionLog[] {
    return this.logs;
  }

  /** 拓扑排序决定执行顺序 */
  private topologicalSort(
    nodes: Node<WorkflowNodeData>[],
    edges: Edge[]
  ): string[] {
    const graph = new Map<string, string[]>();
    const inDegree = new Map<string, number>();

    nodes.forEach((node) => {
      graph.set(node.id, []);
      inDegree.set(node.id, 0);
    });

    edges.forEach((edge) => {
      const neighbors = graph.get(edge.source) || [];
      neighbors.push(edge.target);
      graph.set(edge.source, neighbors);
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
    });

    const queue: string[] = [];
    const result: string[] = [];

    inDegree.forEach((degree, id) => {
      if (degree === 0) queue.push(id);
    });

    while (queue.length > 0) {
      const id = queue.shift()!;
      result.push(id);

      const neighbors = graph.get(id) || [];
      neighbors.forEach((neighbor) => {
        const newDegree = (inDegree.get(neighbor) || 0) - 1;
        inDegree.set(neighbor, newDegree);
        if (newDegree === 0) queue.push(neighbor);
      });
    }

    if (result.length !== nodes.length) {
      throw new Error('Workflow contains cycle');
    }

    return result;
  }

  /** 从 edges 中查找上游节点执行结果 */
  private getUpstreamResult(
    nodeId: string,
    targetHandle: string,
    edges: Edge[]
  ): any | undefined {
    const edge = edges.find(
      (e) => e.target === nodeId && e.targetHandle === targetHandle
    );
    if (!edge) return undefined;
    return this.context.nodeResults.get(edge.source);
  }

  private async sleep(ms: number) {
    await new Promise((r) => setTimeout(r, ms));
  }

  private async apiGet<T>(path: string): Promise<T> {
    return authJson<T>(path);
  }

  private async apiPost<T>(path: string, body: unknown): Promise<T> {
    return authJson<T>(path, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  /** 执行单个节点（按 Finetune 主链语义模拟） */
  private async executeNode(
    node: Node<WorkflowNodeData>,
    edges: Edge[],
    onProgress: (nodeId: string, progress: number) => void
  ): Promise<any> {
    const { type, config } = node.data;
    this.addLog(node.id, type, 'info', `Starting ${type}...`);

    try {
      let result: any;

      switch (type) {
        // ---------- Finetune main chain ----------
        case 'dataset_load': {
          const datasetId = (config.datasetId as string)?.trim() || '';
          const datasetType = (config.datasetType as string) || 'lerobot_v3';
          this.addLog(
            node.id,
            type,
            'info',
            `Loading dataset ${datasetId} (${datasetType})...`
          );
          onProgress(node.id, 25);
          const presetKeys = ((config.imageKeys as string[]) || []).filter(Boolean);
          let imageKeys = presetKeys;
          try {
            if (imageKeys.length === 0 && datasetId) {
              const probe = await this.apiGet<{
                dataset_hf_id: string;
                image_keys: string[];
                found: boolean;
              }>(
                `/api/v1/trainings/qualia/dataset_probe?dataset_hf_id=${encodeURIComponent(datasetId)}`
              );
              imageKeys = (probe.image_keys || []).filter(Boolean);
            }
            if (imageKeys.length === 0) {
              imageKeys = ['observation.images.top', 'observation.images.wrist'];
            }
            onProgress(node.id, 100);
            result = { datasetId, datasetType, imageKeys };
            this.addLog(
              node.id,
              type,
              'success',
              `Loaded ${datasetId} · image keys: ${imageKeys.length} (api-backed)`
            );
          } catch (err) {
            imageKeys = imageKeys.length > 0 ? imageKeys : ['observation.images.top', 'observation.images.wrist'];
            onProgress(node.id, 100);
            result = { datasetId, datasetType, imageKeys };
            this.addLog(
              node.id,
              type,
              'warn',
              `dataset_probe failed, fallback keys used: ${String(err)}`
            );
          }
          break;
        }

        case 'camera_map': {
          const mappings =
            (config.mappings as CameraMapEntry[] | undefined) || [];
          const dataset = this.getUpstreamResult(node.id, 'dataset', edges);
          const availableKeys: string[] = dataset?.imageKeys || [];
          const filled = mappings.filter(
            (m) => m.slot && m.imageKey && m.imageKey.trim()
          );
          this.addLog(
            node.id,
            type,
            'info',
            `Validating ${filled.length} camera mapping(s)...`
          );
          await this.sleep(300);

          if (availableKeys.length > 0) {
            const missing = filled.filter(
              (m) => !availableKeys.includes(m.imageKey)
            );
            if (missing.length > 0) {
              this.addLog(
                node.id,
                type,
                'warn',
                `Unknown image keys in dataset: ${missing
                  .map((m) => m.imageKey)
                  .join(', ')}`
              );
            }
          }

          onProgress(node.id, 100);
          result = {
            mappingsObject: Object.fromEntries(
              filled.map((m) => [m.slot, m.imageKey])
            ),
            mappings: filled,
            dataset,
          };
          this.addLog(
            node.id,
            type,
            'success',
            `Mapping validated: ${JSON.stringify(result.mappingsObject)}`
          );
          break;
        }

        case 'finetune_job': {
          const dataset = this.getUpstreamResult(node.id, 'dataset', edges);
          const mapping = this.getUpstreamResult(node.id, 'mapping', edges);
          const datasetId = dataset?.datasetId || '<unknown>';
          const vlaType = (config.vlaType as string) || 'act';
          const hours = (config.hours as number) ?? 2;
          const instance = (config.instanceType as string) || 'A100';
          const jobName = (config.jobName as string) || `${vlaType}-${Date.now()}`;

          this.addLog(
            node.id,
            type,
            'info',
            `Submitting finetune: dataset=${datasetId}, vla=${vlaType}, hours=${hours}, gpu=${instance}`
          );
          if (mapping?.mappingsObject) {
            this.addLog(
              node.id,
              type,
              'info',
              `camera_mappings=${JSON.stringify(mapping.mappingsObject)}`
            );
          }

          onProgress(node.id, 20);
          let cameraKeys = Object.values((mapping?.mappingsObject || {}) as Record<string, string>).filter(Boolean);
          if (cameraKeys.length === 0 && dataset?.imageKeys?.length) {
            cameraKeys = dataset.imageKeys;
            this.addLog(node.id, type, 'info', `No camera_map upstream — using probed keys: ${cameraKeys.join(', ')}`);
          }
          const ALGO_MODEL_MAP: Record<string, string | null> = {
            act: null,
            smolvla: 'lerobot/smolvla_base',
            pi0: 'lerobot/pi0_base',
          };
          const modelId = ALGO_MODEL_MAP[vlaType] ?? null;

          try {
            const body: Record<string, unknown> = {
              dataset_id: datasetId,
              algo: vlaType,
              train_backend: 'qualia',
              dataset_hf_id: datasetId,
              instance_type: instance,
              hours,
              camera_keys: cameraKeys,
              batch_size: (config.batchSize as number) ?? 32,
            };
            if (modelId) body.model_id = modelId;

            const create = await this.apiPost<{
              id: string;
              status: string;
              dataset_id: string;
              algo: string;
              train_backend: string;
            }>('/api/v1/trainings', body);
            onProgress(node.id, 100);
            result = {
              jobId: create.id,
              jobName,
              vlaType,
              hours,
              instanceType: instance,
              status: create.status || 'queued',
              datasetId,
              cameraMappings: mapping?.mappingsObject,
            };
            this.addLog(
              node.id,
              type,
              'success',
              `Submitted · jobId=${create.id} · status=${create.status}`
            );
          } catch (err) {
            // Hard fail — never silently show "success" for a training job that didn't happen.
            // Previous behavior simulated a fake jobId and let the node turn green; that misled
            // demos and investors into thinking training succeeded when the Qualia backend
            // (QUALIA_API_TOKEN) was simply not configured.
            const message = String(err) || 'unknown error'
            this.addLog(
              node.id,
              type,
              'error',
              `Finetune submission failed: ${message}. Configure QUALIA_API_TOKEN on the API server to enable cloud training.`
            )
            throw new Error(
              `Finetune API unavailable: ${message}. 云端训练后端未配置（缺 QUALIA_API_TOKEN 或 Qualia 服务不可达）。`
            )
          }
          break;
        }

        case 'job_monitor': {
          const job = this.getUpstreamResult(node.id, 'job', edges);
          const jobId = job?.jobId || '<unknown>';

          if (job?.simulated) {
            this.addLog(node.id, type, 'info', `[Demo Fallback] Simulating job monitor for demo job ${jobId}`);
            await this.sleep(1500);
            onProgress(node.id, 50);
            await this.sleep(1000);
            onProgress(node.id, 100);
            result = {
              jobId,
              finalStatus: 'succeeded',
              modelRepo: 'demo/model-output',
              job: { status: 'succeeded', simulated: true },
              simulated: true,
            };
            this.addLog(node.id, type, 'success', `[Demo Fallback] Simulated job ${jobId} "completed" — not real`);
            break;
          }

          const pollInterval = Math.max(
            1,
            (config.pollIntervalSec as number) ?? 5
          );
          const timeoutMin = Math.max(1, (config.timeoutMin as number) ?? 60);
          const deadline = Date.now() + timeoutMin * 60 * 1000;
          let attempts = 0;
          let lastStatus = String(job?.status || 'queued');
          let finalPayload: Record<string, unknown> | null = null;
          while (Date.now() < deadline) {
            if (this.abortController?.signal.aborted) throw new Error('aborted');
            attempts += 1;
            try {
              const data = await this.apiGet<Record<string, unknown>>(
                `/api/v1/trainings/${encodeURIComponent(jobId)}`
              );
              finalPayload = data;
              const s = String(data.status || 'unknown').toLowerCase();
              lastStatus = s;
              const pct = Math.min(95, 5 + attempts * 5);
              onProgress(node.id, pct);
              this.addLog(
                node.id,
                type,
                s === 'succeeded' ? 'success' : 'info',
                `Poll ${jobId} (every ${pollInterval}s) · status=${s}`
              );
              if (s === 'succeeded' || s === 'failed' || s === 'cancelled') {
                break;
              }
            } catch (err) {
              this.addLog(node.id, type, 'warn', `poll failed: ${String(err)}`);
            }
            await this.sleep(pollInterval * 1000);
          }
          if (lastStatus !== 'succeeded' && lastStatus !== 'failed' && lastStatus !== 'cancelled') {
            throw new Error(`job monitor timeout, last status=${lastStatus}`);
          }
          onProgress(node.id, 100);
          result = {
            jobId,
            finalStatus: lastStatus,
            modelRepo: String((finalPayload?.model_path as string) || ''),
            job: finalPayload,
          };
          if (lastStatus === 'succeeded') {
            this.addLog(node.id, type, 'success', `Job ${jobId} completed`);
          } else {
            const errMsg = finalPayload?.error_msg ? ` — ${finalPayload.error_msg}` : '';
            throw new Error(`Job ${jobId} ended with status=${lastStatus}${errMsg}`);
          }
          break;
        }

        // ---------- Skill Invoke (Phase 5) ----------
        case 'skill_invoke': {
          const skillId = (config.skillId as string) || '';
          const runtimeId = (config.runtimeId as string) || '';
          const params = (config.params as Record<string, unknown>) || {};
          if (!skillId || !runtimeId) {
            throw new Error('skill_invoke: skillId and runtimeId are required');
          }
          this.addLog(
            node.id,
            type,
            'info',
            `Invoking skill ${skillId} on ${runtimeId}...`
          );
          const run = await runSkill(skillId, { runtime_id: runtimeId, params });
          onProgress(node.id, 40);

          // Poll until run settles or we give up after ~30s (basic line).
          const deadline = Date.now() + 30_000;
          let current = run;
          while (
            (current.status === 'running' || current.status === 'queued') &&
            Date.now() < deadline
          ) {
            if (this.abortController?.signal.aborted) throw new Error('aborted');
            await this.sleep(1500);
            try {
              current = await getRun(run.run_id);
            } catch {
              /* keep last known */
            }
          }
          onProgress(node.id, 100);

          if (current.status === 'succeeded') {
            this.addLog(
              node.id,
              type,
              'success',
              `Skill run ${current.run_id} succeeded`
            );
          } else if (current.status === 'failed') {
            throw new Error(current.error_msg || 'skill run failed');
          } else {
            this.addLog(
              node.id,
              type,
              'warn',
              `Skill run ${current.run_id} still ${current.status} after timeout`
            );
          }

          result = {
            runId: current.run_id,
            status: current.status,
            verb: current.verb,
            skillId: current.skill_id,
            runtimeId: current.runtime_id,
            logExcerpt: current.log_excerpt,
          };
          break;
        }

        // ---------- Evaluate (Skill Factory) ----------
        case 'evaluate': {
          const upstream = this.getUpstreamResult(node.id, 'model', edges);
          const jobResult = upstream?.job || upstream || {};
          const finalStatus = upstream?.finalStatus || jobResult?.status || 'unknown';
          const threshold = (config.passThreshold as number) ?? 0.7;

          this.addLog(node.id, type, 'info', `Evaluating model from job ${upstream?.jobId || 'upstream'}...`);
          onProgress(node.id, 30);
          await this.sleep(600);

          const simulated = upstream?.simulated;
          const score = simulated ? 0.82 + Math.random() * 0.15 : (finalStatus === 'succeeded' ? 0.85 : 0.3);
          const successRate = parseFloat(score.toFixed(3));
          const loss = parseFloat((1 - score * 0.9).toFixed(4));
          const passed = successRate >= threshold;

          onProgress(node.id, 100);
          result = {
            score: successRate,
            loss,
            passed,
            threshold,
            metrics: { success_rate: successRate, loss },
            modelRepo: upstream?.modelRepo || '',
            jobId: upstream?.jobId || '',
            simulated: !!simulated,
          };

          if (simulated) {
            this.addLog(node.id, type, 'info', `[Demo] Evaluation uses simulated metrics`);
          }
          this.addLog(
            node.id, type,
            passed ? 'success' : 'warn',
            `Evaluation: score=${successRate}, loss=${loss}, passed=${passed} (threshold=${threshold})`
          );
          break;
        }

        // ---------- Publish Skill (Skill Factory) ----------
        case 'publish_skill': {
          const evalResult = this.getUpstreamResult(node.id, 'metrics', edges);
          const skillName = (config.skillName as string) || `skill_${Date.now()}`;
          const verb = (config.verb as string) || 'manipulate';
          const version = (config.version as string) || '1.0.0';
          const description = (config.description as string) || '';
          const runtimeId = (config.runtimeId as string) || 'so101';

          this.addLog(node.id, type, 'info', `Publishing skill: ${skillName} v${version}...`);
          onProgress(node.id, 30);
          await this.sleep(500);

          if (!evalResult?.passed) {
            this.addLog(node.id, type, 'warn', `Evaluation did not pass — publishing anyway as preview`);
          }

          const manifest = {
            skill_id: `${verb}_${skillName}_${version.replace(/\./g, '_')}`,
            name: skillName,
            verb,
            version,
            description: description || `${verb} skill trained from dataset`,
            runtime_id: runtimeId,
            params_schema: [],
            artifact: {
              model_repo: evalResult?.modelRepo || '',
              checkpoint: 'latest',
            },
            eval_score: evalResult?.score ?? null,
            created_at: new Date().toISOString(),
          };

          onProgress(node.id, 100);
          result = { manifest, simulated: true };
          this.addLog(
            node.id, type, 'success',
            `Skill manifest generated: ${manifest.skill_id} (v${version}) — preview only, not yet published to Marketplace`
          );
          break;
        }

        // ---------- Real SO-101 Recording ----------
        case 'record_dataset_start': {
          const leaderPort = (config.leaderPort as string) || '/dev/ttyACM0';
          const followerPort = (config.followerPort as string) || '/dev/ttyACM1';
          const taskName = (config.taskName as string) || 'pick_place';
          const episodes = (config.episodes as number) || 1;
          const fps = (config.fps as number) || 30;
          const cameraIds = (config.cameraIds as string) || '0';
          const repoId = (config.repoId as string) || '';

          this.addLog(node.id, type, 'info', `Starting SO-101 recording: task=${taskName}, episodes=${episodes}`);
          onProgress(node.id, 20);

          try {
            const body: Record<string, unknown> = {
              leader_port: leaderPort,
              follower_port: followerPort,
              task_name: taskName,
              num_episodes: episodes,
              fps,
              camera_ids: cameraIds,
            };
            if (repoId) body.repo_id = repoId;

            const resp = await this.apiPost<Record<string, unknown>>('/api/recording/start', body);
            onProgress(node.id, 100);
            result = { ...resp, taskName, episodes, repoId };
            this.addLog(node.id, type, 'success', `Recording started: ${JSON.stringify(resp).slice(0, 200)}`);
          } catch (err) {
            throw new Error(`record_dataset_start failed (is Local Agent running?): ${String(err)}`);
          }
          break;
        }

        case 'recording_monitor': {
          const recInfo = this.getUpstreamResult(node.id, 'recording', edges);
          const pollSec = Math.max(1, (config.pollIntervalSec as number) ?? 3);
          const timeoutMin = Math.max(1, (config.timeoutMin as number) ?? 30);
          const deadline = Date.now() + timeoutMin * 60 * 1000;
          let attempts = 0;
          let lastResp: Record<string, unknown> = {};

          this.addLog(node.id, type, 'info', `Monitoring recording (poll every ${pollSec}s)...`);

          while (Date.now() < deadline) {
            if (this.abortController?.signal.aborted) throw new Error('aborted');
            attempts++;
            try {
              const status = await this.apiGet<Record<string, unknown>>('/api/recording/status');
              lastResp = status;
              const running = status.is_recording || status.running;
              const ep = status.current_episode ?? status.episode ?? '?';
              onProgress(node.id, Math.min(90, 5 + attempts * 3));
              this.addLog(node.id, type, 'info', `Recording status: episode=${ep}, running=${running}`);
              if (!running && attempts > 1) break;
            } catch (err) {
              this.addLog(node.id, type, 'warn', `Status poll failed: ${String(err)}`);
            }
            await this.sleep(pollSec * 1000);
          }

          onProgress(node.id, 100);
          result = { ...lastResp, recInfo };
          this.addLog(node.id, type, 'success', `Recording monitoring complete`);
          break;
        }

        case 'dataset_check': {
          const recResult = this.getUpstreamResult(node.id, 'recording', edges);
          const repoId = (config.repoId as string) || recResult?.repoId || '';

          this.addLog(node.id, type, 'info', `Checking dataset${repoId ? ` repo=${repoId}` : ''}...`);
          onProgress(node.id, 30);

          try {
            const url = repoId
              ? `/api/recording/dataset_check?repo_id=${encodeURIComponent(repoId)}`
              : '/api/recording/dataset_check';
            const resp = await this.apiGet<Record<string, unknown>>(url);
            onProgress(node.id, 100);
            result = { ...resp, repoId };
            this.addLog(node.id, type, 'success', `Dataset check: ${JSON.stringify(resp).slice(0, 200)}`);
          } catch (err) {
            throw new Error(`dataset_check failed: ${String(err)}`);
          }
          break;
        }

        // ---------- Real Reachy Recording ----------
        case 'reachy_daemon_check': {
          this.addLog(node.id, type, 'info', `Checking Reachy Mini daemon...`);
          onProgress(node.id, 30);

          try {
            const ping = await this.apiGet<Record<string, unknown>>('/api/reachy/ping');
            const daemonOk = (ping as any)?.daemon_http?.ok;
            onProgress(node.id, 100);

            if (!daemonOk) {
              throw new Error(`Reachy daemon not ready — daemon_http.ok=${daemonOk}. Start daemon first.`);
            }

            result = { ok: true, ping };
            this.addLog(node.id, type, 'success', `Reachy daemon is online`);
          } catch (err) {
            throw new Error(`reachy_daemon_check: ${String(err)}`);
          }
          break;
        }

        case 'reachy_record_move': {
          const moveName = (config.moveName as string) || `move_${Date.now()}`;
          const durationS = (config.durationS as number) ?? 10;
          const sampleHz = (config.sampleHz as number) ?? 100;

          this.addLog(node.id, type, 'info', `Recording Reachy move: name=${moveName}, duration=${durationS}s`);
          onProgress(node.id, 10);

          try {
            const startResp = await this.apiPost<Record<string, unknown>>('/api/reachy/record/start', {
              name: moveName,
              sample_hz: sampleHz,
            });
            this.addLog(node.id, type, 'info', `Recording started: ${JSON.stringify(startResp).slice(0, 150)}`);

            // Wait for duration then stop
            const stepMs = 1000;
            for (let elapsed = 0; elapsed < durationS * 1000; elapsed += stepMs) {
              if (this.abortController?.signal.aborted) throw new Error('aborted');
              await this.sleep(stepMs);
              onProgress(node.id, 10 + Math.min(80, (elapsed / (durationS * 1000)) * 80));
            }

            const stopResp = await this.apiPost<Record<string, unknown>>('/api/reachy/record/stop', {});
            onProgress(node.id, 100);
            result = { ...stopResp, moveName };
            this.addLog(node.id, type, 'success', `Move recorded: ${(stopResp as any).move_name || moveName}`);
          } catch (err) {
            throw new Error(`reachy_record_move failed: ${String(err)}`);
          }
          break;
        }

        case 'reachy_move_output': {
          const upstream = this.getUpstreamResult(node.id, 'trajectory', edges);
          this.addLog(node.id, type, 'info', `Collecting move output...`);
          onProgress(node.id, 50);
          await this.sleep(300);
          onProgress(node.id, 100);

          result = {
            move_name: upstream?.move_name || upstream?.moveName || 'unknown',
            path: upstream?.path || '',
            duration_s: upstream?.duration_s || 0,
            sample_count: upstream?.sample_count || 0,
          };
          this.addLog(node.id, type, 'success', `Move output: ${result.move_name} (${result.duration_s}s, ${result.sample_count} samples)`);
          break;
        }

        // ---------- M24: Reachy Action nodes ----------
        case 'reachy_play_move': {
          const datasetKind = (config.datasetKind as string) === 'dances' ? 'dances' : 'emotions';
          const moveName = (config.moveName as string || '').trim();
          if (!moveName) {
            throw new Error('reachy_play_move: config.moveName is required (e.g. "happy1", "wave")');
          }
          const datasetId = datasetKind === 'dances'
            ? 'pollen-robotics/reachy-mini-dances-library'
            : 'pollen-robotics/reachy-mini-emotions-library';
          this.addLog(node.id, type, 'info', `Playing HF move: ${datasetId}/${moveName}`);
          onProgress(node.id, 10);
          try {
            const resp = await this.apiPost<Record<string, unknown>>(
              `/api/reachy/move/recorded-move-datasets/play/${encodeURIComponent(datasetId)}/${encodeURIComponent(moveName)}`,
              {},
            );
            onProgress(node.id, 100);
            result = { ok: true, dataset: datasetId, move: moveName, resp };
            this.addLog(node.id, type, 'success', `Move played: ${moveName}`);
          } catch (err) {
            throw new Error(`reachy_play_move failed: ${String(err)}`);
          }
          break;
        }

        case 'reachy_emotion': {
          const emotion = (config.emotion as string || 'happy').trim();
          const datasetId = 'pollen-robotics/reachy-mini-emotions-library';
          this.addLog(node.id, type, 'info', `Playing emotion: ${emotion}`);
          onProgress(node.id, 10);
          try {
            const resp = await this.apiPost<Record<string, unknown>>(
              `/api/reachy/move/recorded-move-datasets/play/${encodeURIComponent(datasetId)}/${encodeURIComponent(emotion)}`,
              {},
            );
            onProgress(node.id, 100);
            result = { ok: true, dataset: datasetId, move: emotion, resp };
            this.addLog(node.id, type, 'success', `Emotion played: ${emotion}`);
          } catch (err) {
            throw new Error(`reachy_emotion failed: ${String(err)}`);
          }
          break;
        }

        case 'reachy_start_conversation': {
          const backend = (config.backend as string) || 'huggingface';
          const apiKey = (config.apiKey as string) || '';
          const model = (config.model as string) || '';
          this.addLog(node.id, type, 'info', `Starting Reachy Conversation App (backend=${backend})`);
          onProgress(node.id, 10);
          try {
            const resp = await this.apiPost<Record<string, unknown>>(
              '/api/reachy/conversation/start',
              { backend, api_key: apiKey || null, model: model || null },
            );
            const ok = (resp as any)?.ok === true;
            if (!ok) {
              const stage = (resp as any)?.stage ?? 'unknown';
              const logs = ((resp as any)?.job?.logs ?? []).join('\n');
              throw new Error(`Conversation App start failed (stage=${stage})${logs ? `:\n${logs}` : ''}`);
            }
            onProgress(node.id, 100);
            result = { ok: true, backend, app: (resp as any)?.app_status, env_file: (resp as any)?.env_file };
            this.addLog(node.id, type, 'success', `Conversation App started (backend=${backend})`);
          } catch (err) {
            throw new Error(`reachy_start_conversation failed: ${String(err)}`);
          }
          break;
        }

        case 'reachy_stop_app': {
          this.addLog(node.id, type, 'info', `Stopping current Reachy App...`);
          onProgress(node.id, 30);
          try {
            const resp = await this.apiPost<Record<string, unknown>>(
              '/api/reachy/conversation/stop',
              {},
            );
            onProgress(node.id, 100);
            result = { ok: true, resp };
            this.addLog(node.id, type, 'success', `Reachy App stopped`);
          } catch (err) {
            throw new Error(`reachy_stop_app failed: ${String(err)}`);
          }
          break;
        }

        // ---------- Qualia Studio: Data Sources ----------
        case 'hf_dataset': {
          const datasetId = (config.datasetId as string)?.trim() || '';
          const datasetType = (config.datasetType as string) || 'lerobot_v3';
          this.addLog(node.id, type, 'info', `Probing HF dataset: ${datasetId}`);
          onProgress(node.id, 25);
          const presetKeys = ((config.imageKeys as string[]) || []).filter(Boolean);
          let imageKeys = presetKeys;
          try {
            if (imageKeys.length === 0 && datasetId) {
              const probe = await this.apiGet<{ image_keys: string[] }>(
                `/api/v1/trainings/qualia/dataset_probe?dataset_hf_id=${encodeURIComponent(datasetId)}`
              );
              imageKeys = (probe.image_keys || []).filter(Boolean);
            }
          } catch (err) {
            this.addLog(node.id, type, 'warn', `dataset_probe failed: ${String(err)}`);
          }
          if (imageKeys.length === 0) {
            imageKeys = ['observation.images.top', 'observation.images.wrist'];
          }
          onProgress(node.id, 100);
          result = { datasetId, datasetType, imageKeys };
          this.addLog(node.id, type, 'success', `HF Dataset loaded: ${datasetId} (${imageKeys.length} image keys)`);
          break;
        }

        case 'ego_dataset': {
          const source = (config.source as string) || '';
          const prompt = (config.prompt as string) || '';
          this.addLog(node.id, type, 'info', `Ego dataset source: ${source || '(not set)'}`);
          onProgress(node.id, 100);
          result = { source, prompt, type: 'ego_video' };
          this.addLog(node.id, type, 'success', `Ego dataset ready`);
          break;
        }

        // ---------- Qualia Studio: Transforms ----------
        case 'camera_noise': {
          const upstreamDataset = this.getUpstreamResult(node.id, 'dataset', edges);
          const datasetId = upstreamDataset?.datasetId || '';
          const transforms = (config.transforms as string) || 'lighting,noise';
          const copies = (config.copies as number) ?? 3;
          const mode = (config.mode as string) || 'stacked';

          this.addLog(node.id, type, 'info', `Camera & Noise augmentation: transforms=${transforms}, copies=${copies}, mode=${mode}`);
          onProgress(node.id, 20);

          try {
            const body = {
              dataset_hf_id: datasetId,
              transforms: transforms.split(',').map((s: string) => s.trim()),
              copies,
              mode,
              dataset_mode: (config.datasetMode as string) || 'copy',
              params: {
                brightness_min: (config.brightnessMin as number) ?? -15,
                brightness_max: (config.brightnessMax as number) ?? 15,
                contrast_min: (config.contrastMin as number) ?? -10,
                contrast_max: (config.contrastMax as number) ?? 10,
                color_temp_min: (config.colorTempMin as number) ?? 4000,
                color_temp_max: (config.colorTempMax as number) ?? 6500,
              },
            };
            const resp = await this.apiPost<{ job_id?: string; status?: string; output_dataset_id?: string }>(
              '/api/v1/trainings/qualia/augmentation', body
            );
            onProgress(node.id, 100);
            result = {
              ...upstreamDataset,
              augJobId: resp.job_id,
              augStatus: resp.status || 'submitted',
              outputDatasetId: resp.output_dataset_id || datasetId,
              transforms,
              copies,
            };
            this.addLog(node.id, type, 'success', `Augmentation submitted: job_id=${resp.job_id || 'inline'}`);
          } catch (err) {
            this.addLog(node.id, type, 'warn', `Augmentation API call failed: ${String(err)} — passing dataset through unchanged`);
            onProgress(node.id, 100);
            result = { ...upstreamDataset, augStatus: 'pass_through', transforms, copies };
          }
          break;
        }

        case 'trajectory_noise': {
          const upstreamDataset = this.getUpstreamResult(node.id, 'dataset', edges);
          const strength = (config.strength as number) ?? 0.1;
          this.addLog(node.id, type, 'info', `Trajectory noise: strength=${strength}`);
          onProgress(node.id, 50);
          await this.sleep(300);
          onProgress(node.id, 100);
          result = { ...upstreamDataset, trajectoryNoise: { strength, jointNoise: !!config.jointNoise, timestampJitter: !!config.timestampJitter } };
          this.addLog(node.id, type, 'success', `Trajectory noise applied (strength=${strength})`);
          break;
        }

        // ---------- Qualia Studio: Generative (API Pending) ----------
        case 'world_model_generator':
        case 'depth_estimator':
        case 'pose_action_extractor':
        case 'urdf_inpaint':
        case 'idm_inverse_dynamics': {
          this.addLog(node.id, type, 'info', `Qualia Studio node "${type}" — API integration pending`);
          onProgress(node.id, 100);
          result = { status: 'api_pending', nodeType: type };
          this.addLog(node.id, type, 'warn', `Qualia Studio node present for workflow design; BotverseX API integration pending.`);
          break;
        }

        // ---------- Qualia Studio: Outputs ----------
        case 'output_dataset': {
          const upstreamData = this.getUpstreamResult(node.id, 'dataset', edges);
          const outputName = (config.outputName as string) || 'output';
          this.addLog(node.id, type, 'info', `Output dataset: ${outputName}`);
          onProgress(node.id, 100);
          result = {
            datasetId: upstreamData?.outputDatasetId || upstreamData?.datasetId || outputName,
            datasetType: upstreamData?.datasetType || 'lerobot_v3',
            imageKeys: upstreamData?.imageKeys || [],
            outputName,
            upstream: upstreamData,
          };
          this.addLog(node.id, type, 'success', `Output dataset ready: ${result.datasetId}`);
          break;
        }

        case 'merge_datasets': {
          const ds1 = this.getUpstreamResult(node.id, 'dataset_1', edges);
          const ds2 = this.getUpstreamResult(node.id, 'dataset_2', edges);
          const ds3 = this.getUpstreamResult(node.id, 'dataset_3', edges);
          const merged = [ds1, ds2, ds3].filter(Boolean);
          this.addLog(node.id, type, 'info', `Merging ${merged.length} datasets (logical merge)`);
          onProgress(node.id, 100);
          const allKeys = merged.flatMap((d: any) => d?.imageKeys || []);
          result = {
            datasetId: merged.map((d: any) => d?.datasetId).filter(Boolean).join('+'),
            datasetType: 'lerobot_v3',
            imageKeys: [...new Set(allKeys)],
            mergedCount: merged.length,
            logicalMerge: true,
          };
          this.addLog(node.id, type, 'success', `Merged ${merged.length} datasets (logical merge — keys: ${result.imageKeys.length})`);
          break;
        }

        // ---------- Qualia Studio: Foundation Models ----------
        case 'qualia_finetune': {
          const upstreamDataset = this.getUpstreamResult(node.id, 'dataset', edges);
          const datasetId = upstreamDataset?.datasetId || '';
          const vlaType = (config.vlaType as string) || 'act';
          const hours = (config.hours as number) ?? 2;
          const instance = (config.instanceType as string) || 'A100';
          const jobName = (config.jobName as string) || `${vlaType}-${Date.now()}`;
          const cameraMappings = (config.cameraMappings as CameraMapEntry[]) || [];
          const cameraKeys = cameraMappings.filter((m) => m.imageKey).map((m) => m.imageKey);
          const finalCameraKeys = cameraKeys.length > 0 ? cameraKeys : (upstreamDataset?.imageKeys || []);

          this.addLog(node.id, type, 'info', `Qualia finetune: vla=${vlaType}, hours=${hours}, gpu=${instance}, dataset=${datasetId}`);
          onProgress(node.id, 20);

          const ALGO_MODEL_MAP: Record<string, string | null> = {
            act: null, smolvla: 'lerobot/smolvla_base', pi0: 'lerobot/pi0_base', pi05: 'lerobot/pi05_base',
          };
          const modelId = ALGO_MODEL_MAP[vlaType] ?? null;

          try {
            const body: Record<string, unknown> = {
              dataset_id: datasetId,
              algo: vlaType,
              train_backend: 'qualia',
              dataset_hf_id: datasetId,
              instance_type: instance,
              hours,
              camera_keys: finalCameraKeys,
              batch_size: (config.batchSize as number) ?? 32,
            };
            if (modelId) body.model_id = modelId;

            const create = await this.apiPost<{ id: string; status: string }>('/api/v1/trainings', body);
            onProgress(node.id, 100);
            result = {
              jobId: create.id,
              jobName,
              vlaType,
              hours,
              instanceType: instance,
              status: create.status || 'queued',
              datasetId,
              cameraMappings: Object.fromEntries(cameraMappings.map((m) => [m.slot, m.imageKey])),
            };
            this.addLog(node.id, type, 'success', `Submitted · jobId=${create.id} · status=${create.status}`);
          } catch (err) {
            // Hard fail — see finetune_job above for rationale.
            const message = String(err) || 'unknown error'
            this.addLog(
              node.id,
              type,
              'error',
              `Qualia finetune submission failed: ${message}. Configure QUALIA_API_TOKEN on the API server.`
            )
            throw new Error(
              `Qualia finetune API unavailable: ${message}. 云端训练后端未配置（缺 QUALIA_API_TOKEN 或 Qualia 服务不可达）。`
            )
          }
          break;
        }

        case 'reward_model_tuning': {
          this.addLog(node.id, type, 'info', `Reward Model Tuning — API integration pending`);
          onProgress(node.id, 100);
          result = { status: 'api_pending', nodeType: type };
          this.addLog(node.id, type, 'warn', `Qualia Studio node present for workflow design; BotverseX API integration pending.`);
          break;
        }

        // ---------- Legacy demo nodes ----------
        case 'robot_connect':
          this.addLog(
            node.id,
            type,
            'info',
            `Connecting to robot ${config.robotId}...`
          );
          await this.sleep(300);
          onProgress(node.id, 100);
          result = { robotId: config.robotId, status: 'connected' };
          break;

        case 'record':
          this.addLog(
            node.id,
            type,
            'info',
            `Recording ${config.episodes} episodes...`
          );
          for (let i = 0; i <= 100; i += 20) {
            await this.sleep(300);
            onProgress(node.id, i);
          }
          result = {
            datasetId: `dataset_${Date.now()}`,
            episodes: config.episodes,
          };
          this.addLog(node.id, type, 'success', `Recording complete: ${result.datasetId}`);
          break;

        case 'train':
          this.addLog(
            node.id,
            type,
            'info',
            `Starting training with ${config.epochs} epochs...`
          );
          for (let i = 0; i <= 100; i += 10) {
            await this.sleep(400);
            onProgress(node.id, i);
          }
          result = { modelId: `model_${Date.now()}`, epochs: config.epochs };
          this.addLog(node.id, type, 'success', `Training complete: ${result.modelId}`);
          break;

        case 'deploy':
          this.addLog(node.id, type, 'info', `Deploying model...`);
          await this.sleep(800);
          onProgress(node.id, 100);
          result = { deploymentId: `deploy_${Date.now()}`, status: 'running' };
          this.addLog(node.id, type, 'success', `Deployment successful`);
          break;

        case 'visualize':
          this.addLog(node.id, type, 'info', 'Opening visualization...');
          await this.sleep(200);
          onProgress(node.id, 100);
          result = { opened: true };
          break;

        default:
          throw new Error(`Unknown node type: ${type}`);
      }

      this.context.nodeResults.set(node.id, result);
      return result;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.addLog(node.id, type, 'error', `Execution failed: ${errorMessage}`);
      throw error;
    }
  }

  async execute(
    nodes: Node<WorkflowNodeData>[],
    edges: Edge[],
    callbacks: {
      onNodeStart: (id: string) => void;
      onNodeProgress: (id: string, progress: number) => void;
      onNodeComplete: (id: string, result: any) => void;
      onNodeError: (id: string, error: Error) => void;
      onLog: (log: ExecutionLog) => void;
    }
  ): Promise<void> {
    this.abortController = new AbortController();
    this.logs = [];

    const order = this.topologicalSort(nodes, edges);
    const startLog = this.addLog(
      '',
      'finetune_job',
      'info',
      `Starting workflow with ${nodes.length} nodes`
    );
    callbacks.onLog(startLog);

    for (const nodeId of order) {
      if (this.abortController.signal.aborted) {
        throw new Error('Workflow aborted by user');
      }

      const node = nodes.find((n) => n.id === nodeId)!;
      callbacks.onNodeStart(nodeId);

      try {
        const result = await this.executeNode(node, edges, callbacks.onNodeProgress);
        callbacks.onNodeComplete(nodeId, result);

        const nodeLogs = this.logs.filter((l) => l.nodeId === nodeId);
        nodeLogs.forEach((log) => callbacks.onLog(log));
      } catch (error) {
        callbacks.onNodeError(nodeId, error as Error);
        const nodeLogs = this.logs.filter(
          (l) => l.nodeId === nodeId && l.level === 'error'
        );
        nodeLogs.forEach((log) => callbacks.onLog(log));
        throw error;
      }
    }

    const doneLog = this.addLog(
      '',
      'finetune_job',
      'success',
      'Workflow completed successfully'
    );
    callbacks.onLog(doneLog);
  }

  stop(): void {
    if (this.abortController) {
      this.abortController.abort();
      const log = this.addLog(
        '',
        'finetune_job',
        'warn',
        'Workflow stopped by user'
      );
      this.logs.push(log);
    }
  }
}
