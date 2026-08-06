// 渲染进程侧的 RPC 封装。
// 唯一职责：把 window.workshop 的 invoke 结果整理成 {ok, result, error}，
// 并把后端错误码翻成可执行的英文提示（默认语言，见 i18n.js）。前端不解析
// error.message 字符串（§3.3）。

import { t } from './i18n.js';

function codeHints() {
  return {
    2: { title: t('status.codeInvalidParamsTitle'), hint: t('status.codeInvalidParamsHint') },
    3: { title: t('status.codeNotFoundTitle'), hint: t('status.codeNotFoundHint') },
    4: { title: t('status.actionFailed'), hint: t('status.codeFailedHint') },
    5: { title: t('status.codeUnavailableTitle'), hint: t('status.codeUnavailableHint') },
    6: { title: t('status.codePartialTitle'), hint: t('status.codePartialHint') },
    7: { title: t('status.codeRejectedTitle'), hint: t('status.codeRejectedHint') },
  };
}

export function describeError(rpc) {
  const meta = codeHints()[rpc?.code] ?? { title: t('status.codeUnknownTitle'), hint: '' };
  return { code: rpc?.code ?? 4, message: rpc?.message ?? '', ...meta };
}

class Rpc extends EventTarget {
  constructor() {
    super();
    this.available = typeof window.workshop !== 'undefined';
    this.status = this.available ? 'starting' : 'down';
    this.progress = new Map();

    if (!this.available) return;

    window.workshop.on('status', ({ status, detail }) => {
      this.status = status;
      this.dispatchEvent(new CustomEvent('status', { detail: { status, detail } }));
    });
    window.workshop.on('log', (line) => {
      this.dispatchEvent(new CustomEvent('log', { detail: line }));
    });
    window.workshop.on('notification', (msg) => {
      if (msg.method === 'progress') {
        // 两种进度：请求内进度用 request，任务进度用 job（BACKEND_PLAN_V2.md §1.2）。
        const { request, job, done, total } = msg.params;
        this.progress.set(job ?? request, { done, total });
        this.dispatchEvent(new CustomEvent('progress', { detail: msg.params }));
      } else if (msg.method === 'job.done') {
        this.progress.delete(msg.params.job);
        this.dispatchEvent(new CustomEvent('job.done', { detail: msg.params }));
      }
    });
  }

  async call(method, params = {}) {
    if (!this.available) {
      return { ok: false, error: describeError({ code: 5, message: t('status.notInElectron') }) };
    }
    const reply = await window.workshop.call(method, params);
    if (!reply.ok) {
      const error = describeError(reply.error);
      this.dispatchEvent(new CustomEvent('error', { detail: error }));
      return { ok: false, error };
    }
    return { ok: true, envelope: reply.envelope, result: reply.envelope.result };
  }

  restart() {
    return window.workshop?.restartSidecar();
  }

  openProjectDialog() {
    return window.workshop?.openProjectDialog();
  }

  pickVideo() {
    return window.workshop?.openFileDialog({
      title: t('common.selectVideo'),
      extensions: ['mp4', 'mov', 'webm', 'mkv', 'avi', 'gif'],
    });
  }

  defaultProject() {
    return window.workshop?.defaultProject() ?? null;
  }
}

export const rpc = new Rpc();
