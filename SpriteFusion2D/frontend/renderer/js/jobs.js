// 任务store —— FRONTEND_PLAN_V2.md §2
//
// 长操作（生成、视频）的契约：提交立刻返回 {job}，进度走通知，完成走 job.done。
// 关键约束：**任务运行期间界面必须全程可用**。所以这里不阻塞任何东西，
// 只维护一张表并派发事件，由任务条和发起面板各自订阅。

import { rpc, describeError } from './rpc.js';

class JobStore extends EventTarget {
  constructor() {
    super();
    this.jobs = new Map(); // id -> {id, label, stage, done, total, startedAt}
    this._waiters = new Map(); // id -> {resolve, reject}

    rpc.addEventListener('progress', (e) => {
      const { job, stage, done, total } = e.detail;
      if (!job) return; // 请求内进度不归这里管
      const entry = this.jobs.get(job);
      if (!entry) return;
      Object.assign(entry, { stage, done, total });
      this._changed();
    });

    rpc.addEventListener('job.done', (e) => {
      const { job, ok, result, error } = e.detail;
      const entry = this.jobs.get(job);
      this.jobs.delete(job);
      this._changed();

      const waiter = this._waiters.get(job);
      this._waiters.delete(job);
      if (!waiter) return;
      if (ok) waiter.resolve({ ok: true, result, label: entry?.label });
      else waiter.reject(Object.assign(new Error(error?.message ?? '任务失败'), { rpc: error }));
    });
  }

  get active() {
    return [...this.jobs.values()];
  }

  _changed() {
    this.dispatchEvent(new CustomEvent('change', { detail: this.active }));
  }

  /**
   * 提交一个任务。返回 {job, promise}。
   * promise 在 job.done 到达时结算——**调用方可以选择不 await**，
   * 界面不应该因为等任务而卡住。
   */
  async submit(method, params = {}, { label = '处理中' } = {}) {
    const reply = await rpc.call(method, params);
    if (!reply.ok) return { job: null, error: reply.error, promise: Promise.reject(reply.error) };

    const id = reply.result?.job;
    if (!id) {
      // 后端没有走任务模型（例如真实 daemon 还没实现），当成同步结果处理
      return { job: null, promise: Promise.resolve({ ok: true, result: reply.result }) };
    }

    const entry = {
      id,
      label: reply.result.label ?? label,
      stage: '排队中',
      done: 0,
      total: 0,
      startedAt: Date.now(),
    };
    this.jobs.set(id, entry);
    this._changed();

    const promise = new Promise((resolve, reject) => {
      this._waiters.set(id, { resolve, reject });
    });
    return { job: id, promise };
  }

  async cancel(id) {
    const reply = await rpc.call('job.cancel', { job: id });
    return reply.ok;
  }

  /** 供任务条显示：阶段名 + 计数，不显示百分比小数（§2.2）。 */
  static describe(entry) {
    if (!entry) return '';
    const count = entry.total > 0 ? ` ${entry.done}/${entry.total}` : '';
    return `${entry.label} · ${entry.stage}${count}`;
  }

  static ratio(entry) {
    if (!entry || !entry.total) return 0;
    return Math.max(0, Math.min(1, entry.done / entry.total));
  }
}

export const jobs = new JobStore();
export { describeError };
