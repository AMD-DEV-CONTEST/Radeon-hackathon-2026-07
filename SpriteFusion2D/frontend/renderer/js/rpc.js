// 渲染进程侧的 RPC 封装。
// 唯一职责：把 window.workshop 的 invoke 结果整理成 {ok, result, error}，
// 并把后端错误码翻成可执行的中文提示。前端不解析 error.message 字符串（§3.3）。

const CODE_HINTS = {
  2: { title: '参数不合法', hint: '检查面板里的参数组合，或换一组默认值重试。' },
  3: { title: '找不到目标', hint: '资产或项目可能已被外部删除，试试重新打开项目。' },
  4: { title: '操作失败', hint: '这一步没有改动项目。展开诊断信息查看细节。' },
  5: { title: '后端不可用', hint: '可选依赖未安装或后端进程已退出。到 doctor 面板查看。' },
  6: { title: '部分成功', hint: '已提交成功的部分，失败项见警告列表。' },
  7: { title: '被拒绝', hint: '拒绝覆盖、路径越界或项目被占用。' },
};

export function describeError(rpc) {
  const meta = CODE_HINTS[rpc?.code] ?? { title: '未知错误', hint: '' };
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
      return { ok: false, error: describeError({ code: 5, message: '未在 Electron 中运行' }) };
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
      title: '选择视频',
      extensions: ['mp4', 'mov', 'webm', 'mkv', 'avi', 'gif'],
    });
  }

  defaultProject() {
    return window.workshop?.defaultProject() ?? null;
  }
}

export const rpc = new Rpc();
