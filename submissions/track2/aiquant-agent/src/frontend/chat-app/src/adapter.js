// ChatModelAdapter — 对接 aiQuant 后端 API
// 支持：普通对话（POST）+ 因子挖掘（SSE 流式）+ 论文上传

const API_BASE = ''; // 同源部署：前端由 FastAPI 挂载于 /，API 走相对路径

const MINING_KEYWORDS = [
  '挖掘', '因子', '回测', '迭代', '沪深300', '中证500', '横截面',
  '低换手', '动量', '反转', '价值', '质量', '波动率', '选股',
];

export function isMiningRequest(text) {
  return MINING_KEYWORDS.some(kw => text.includes(kw));
}

/** 解析 SSE data 行 → 可读 markdown（所有内部字段名中文化，不暴露英文 key） */
function formatSSEEvent(data) {
  try {
    let parsed = data;
    if (typeof data === 'string') {
      const t = data.trim();
      if (t.startsWith('{')) parsed = JSON.parse(t);
      else return data;
    }

    // 提取 content（优先级：content > message > text）
    const content = parsed.content || parsed.message || parsed.text || '';
    // 提取耗时
    const elapsed = parsed.elapsed_sec != null ? `（已耗时 ${parsed.elapsed_sec}s）` : '';

    switch (parsed.type) {
      case 'task_start':
      case 'task_submitted':
        return `${content || '任务已启动'}\n${elapsed}\n\n`;
      case 'memory':
      case 'phase':
      case 'hypothesis':
      case 'code':
      case 'backtest':
      case 'review':
      case 'feedback':
      case 'optimization':
        return `${content}\n${elapsed}\n\n`;
      case 'visual_link': {
        const url = parsed.meta?.ui_url || parsed.url || parsed.link || '';
        return `${content}\n${url ? `🔗 [点击打开可视化面板](${url})\n` : ''}\n`;
      }
      case 'recovery':
        return `${content || '已恢复任务连接'}\n${elapsed}\n\n`;
      case 'final_report':
        return `---\n${content || '任务报告生成完毕'}\n${elapsed}\n`;
      case 'done':
        return `\n✅ **任务完成** ${elapsed}\n`;
      case 'error':
        return `\n❌ ${content || parsed.message || '发生错误'}\n${elapsed}\n`;
      case 'warning':
        return `\n⚠️ ${content || parsed.message || '警告'}\n${elapsed}\n`;
      default:
        // 兜底：只显示 content，不暴露内部 JSON 结构
        if (content) return `${content}\n${elapsed}\n`;
        return '';
    }
  } catch {
    return typeof data === 'string' ? data : '';
  }
}

/**
 * 创建 adapter，供 assistant-ui useLocalRuntime 使用
 * @param {{ onTurnComplete?: (user, assistant) => void }} callbacks
 */
export function createAdapter({ onTurnComplete } = {}) {
  return {
    async *run({ messages, abortSignal }) {
      const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
      if (!lastUserMsg) {
        yield { content: [{ type: 'text', text: '请输入您的问题。' }] };
        return;
      }

      const userText = lastUserMsg.content
        .filter(p => p.type === 'text')
        .map(p => p.text)
        .join('\n');

      let fullReply = '';
      const gen = isMiningRequest(userText)
        ? streamMining(userText, abortSignal)
        : regularChat(userText, abortSignal);

      for await (const text of gen) {
        fullReply = text;
        yield { content: [{ type: 'text', text }] };
      }

      // 通知外层 turn 完成（仅当最后一条消息是 user 时，避免重新生成导致重复）
      const lastMsg = messages[messages.length - 1];
      if (onTurnComplete && fullReply && lastMsg?.role === 'user') {
        const now = Date.now();
        onTurnComplete(
          { role: 'user', text: userText, ts: now },
          { role: 'assistant', text: fullReply, ts: now + 1 }
        );
      }
    },
  };
}

/** SSE 流式因子挖掘 */
async function* streamMining(message, abortSignal) {
  let response;
  try {
    response = await fetch(`${API_BASE}/api/robot/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: 'assistant-ui', message }),
      signal: abortSignal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return;
    yield `❌ 连接失败: ${e.message}`;
    return;
  }

  if (!response.ok) {
    yield `❌ 请求失败 (${response.status}): ${response.statusText}`;
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';

  try {
    while (true) {
      if (abortSignal?.aborted) { reader.cancel(); return; }
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') {
          accumulated += '\n✅ **任务完成**\n';
          yield accumulated;
          return;
        }
        accumulated += formatSSEEvent(data);
        yield accumulated;
      }
    }
    if (buffer) { accumulated += buffer; yield accumulated; }

    // 流正常结束但未收到 [DONE] — 可能是服务端超时断开
    if (!accumulated.includes('任务完成') && !accumulated.includes('任务失败')) {
      const taskIdMatch = accumulated.match(/TASK-[A-Z0-9-]+/);
      if (taskIdMatch) {
        const taskId = taskIdMatch[0];
        accumulated += `\n\n⚠️ **SSE 连接已断开** — 正在通过轮询恢复任务进度...\n`;
        yield accumulated;

        const POLL_INTERVAL = 10000;
        const MAX_POLLS = 60;
        for (let i = 0; i < MAX_POLLS; i++) {
          if (abortSignal?.aborted) return;
          try {
            const statusRes = await fetch(`${API_BASE}/api/tasks/${taskId}/status`);
            if (statusRes.ok) {
              const statusData = await statusRes.json();
              const status = statusData.status;
              const stage = statusData.stage || '';
              const seq = statusData.seq || 0;
              const content = statusData.content || '';
              const elapsed = statusData.elapsed_sec != null ? `（已耗时 ${statusData.elapsed_sec}s）` : '';

              if (status === 'completed' || status === 'failed') {
                accumulated += `---\n`;
                accumulated += status === 'completed'
                  ? `✅ **任务完成** ${elapsed}\n`
                  : `❌ **任务失败** ${elapsed}\n`;
                if (content) accumulated += `${content}\n`;
                yield accumulated;
                return;
              } else if (status === 'running' && i % 3 === 0) {
                accumulated += `⏳ 任务运行中 — 阶段: ${stage}, 序号: ${seq} ${elapsed}\n`;
                yield accumulated;
              }
            }
          } catch (pollErr) {
            // 继续重试
          }
          await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
        }
        accumulated += `\n⏰ 轮询超时（10分钟），任务可能仍在运行。请刷新页面查看最新状态。\n`;
        yield accumulated;
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    // "Error in input stream" 通常意味着 SSE 连接被服务端中断
    const isStreamError = e.message?.includes('input stream') || e.message?.includes('network');
    if (isStreamError) {
      accumulated += `\n\n⚠️ **连接中断** — 正在尝试恢复任务进度...\n`;
      yield accumulated;

      // 尝试从 SSE 事件中提取 task_id
      const taskIdMatch = accumulated.match(/TASK-[A-Z0-9-]+/);
      if (taskIdMatch) {
        const taskId = taskIdMatch[0];
        accumulated += `正在通过轮询恢复任务 \`${taskId}\` 的进度...\n\n`;
        yield accumulated;

        // 轮询恢复：每 10s 查询一次任务状态，直到任务完成或失败
        const POLL_INTERVAL = 10000;
        const MAX_POLLS = 60; // 最多轮询 10 分钟
        for (let i = 0; i < MAX_POLLS; i++) {
          if (abortSignal?.aborted) return;
          try {
            const statusRes = await fetch(`${API_BASE}/api/tasks/${taskId}/status`);
            if (statusRes.ok) {
              const statusData = await statusRes.json();
              const status = statusData.status;
              const stage = statusData.stage || '';
              const seq = statusData.seq || 0;
              const content = statusData.content || '';
              const elapsed = statusData.elapsed_sec != null ? `（已耗时 ${statusData.elapsed_sec}s）` : '';

              if (status === 'completed' || status === 'failed') {
                accumulated += `---\n`;
                accumulated += status === 'completed'
                  ? `✅ **任务完成** ${elapsed}\n`
                  : `❌ **任务失败** ${elapsed}\n`;
                if (content) accumulated += `${content}\n`;
                yield accumulated;
                return;
              } else if (status === 'running') {
                // 每 30s 输出一次进度更新
                if (i % 3 === 0) {
                  accumulated += `⏳ 任务运行中 — 阶段: ${stage}, 序号: ${seq} ${elapsed}\n`;
                  yield accumulated;
                }
              }
            }
          } catch (pollErr) {
            // 轮询失败，继续重试
          }
          await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
        }
        accumulated += `\n⏰ 轮询超时（10分钟），任务可能仍在运行。请刷新页面查看最新状态。\n`;
        yield accumulated;
        return;
      }

      accumulated += `可能原因：\n`;
      accumulated += `• 回测进程仍在运行，但 SSE 连接超时（正常现象，回测完成后可查看结果）\n`;
      accumulated += `• Celery Worker 崩溃或 LLM API 超时\n`;
      accumulated += `• RD-Agent 回测执行异常终止\n\n`;
      accumulated += `💡 可在 RD-Agent 可视化面板（端口 19899）查看任务进度和日志。\n`;
      accumulated += `任务仍在后台运行，不受前端连接断开影响。\n`;
    } else {
      accumulated += `\n❌ 流读取错误: ${e.message}\n`;
    }
    yield accumulated;
  }
}

/** 普通对话 */
async function* regularChat(message, abortSignal) {
  try {
    const res = await fetch(`${API_BASE}/api/robot/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: 'assistant-ui', message }),
      signal: abortSignal,
    });
    if (!res.ok) { yield `❌ 请求失败 (${res.status})`; return; }
    const data = await res.json();
    yield data.reply || data.message || JSON.stringify(data);
  } catch (e) {
    if (e.name === 'AbortError') return;
    yield `❌ 请求失败: ${e.message}`;
  }
}

/** 论文上传 */
export async function uploadPaper(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/api/robot/upload-paper`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`上传失败 (${res.status}): ${errText}`);
  }
  return res.json();
}

/**
 * 检查是否有正在运行的任务，如果有则返回 task_id 供恢复连接。
 * 页面加载时调用此函数，发现运行中任务后自动建立 SSE 连接恢复进度。
 * @returns {Promise<string|null>} 运行中的 task_id 或 null
 */
export async function checkActiveTask() {
  try {
    const res = await fetch(`${API_BASE}/api/tasks/active`);
    if (!res.ok) return null;
    const data = await res.json();
    const active = data.active_tasks || [];
    if (active.length > 0) {
      return active[0]; // 返回第一个活跃任务
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 恢复运行中任务的 SSE 连接。
 * 返回一个 async generator，产出格式化后的进度文本。
 * @param {string} taskId
 * @param {AbortSignal} [abortSignal]
 */
export async function* resumeTaskStream(taskId, abortSignal) {
  let response;
  try {
    response = await fetch(`${API_BASE}/api/tasks/${taskId}/events`, {
      signal: abortSignal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return;
    yield `❌ 恢复连接失败: ${e.message}`;
    return;
  }

  if (!response.ok) {
    yield `❌ 恢复连接失败 (${response.status}): ${response.statusText}`;
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';

  try {
    while (true) {
      if (abortSignal?.aborted) { reader.cancel(); return; }
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        if (line.startsWith(': ')) continue; // heartbeat comment
        const data = line.slice(6);
        if (data === '[DONE]') {
          accumulated += '\n✅ **任务完成**\n';
          yield accumulated;
          return;
        }
        accumulated += formatSSEEvent(data);
        yield accumulated;
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    const isStreamError = e.message?.includes('input stream') || e.message?.includes('network');
    if (isStreamError) {
      accumulated += `\n\n⚠️ **连接中断** — 正在尝试通过轮询恢复...\n`;
      yield accumulated;

      // 轮询恢复
      const POLL_INTERVAL = 10000;
      const MAX_POLLS = 60;
      for (let i = 0; i < MAX_POLLS; i++) {
        if (abortSignal?.aborted) return;
        try {
          const statusRes = await fetch(`${API_BASE}/api/tasks/${taskId}/status`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            const status = statusData.status;
            const stage = statusData.stage || '';
            const seq = statusData.seq || 0;
            const content = statusData.content || '';
            const elapsed = statusData.elapsed_sec != null ? `（已耗时 ${statusData.elapsed_sec}s）` : '';

            if (status === 'completed' || status === 'failed') {
              accumulated += `---\n`;
              accumulated += status === 'completed'
                ? `✅ **任务完成** ${elapsed}\n`
                : `❌ **任务失败** ${elapsed}\n`;
              if (content) accumulated += `${content}\n`;
              yield accumulated;
              return;
            } else if (status === 'running' && i % 3 === 0) {
              accumulated += `⏳ 任务运行中 — 阶段: ${stage}, 序号: ${seq} ${elapsed}\n`;
              yield accumulated;
            }
          }
        } catch {
          // 继续重试
        }
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
      }
      accumulated += `\n⏰ 轮询超时，任务可能仍在运行。请刷新页面查看最新状态。\n`;
      yield accumulated;
    } else {
      accumulated += `\n❌ 流读取错误: ${e.message}\n`;
      yield accumulated;
    }
  }
}
