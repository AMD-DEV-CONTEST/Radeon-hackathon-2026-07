'use strict';
// Sidecar 客户端：JSON-RPC over stdio。
// 只有主进程持有它；渲染进程永远拿不到子进程句柄（FRONTEND_PLAN.md §3, §9.1）。

const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');

const ERR_BACKEND_DOWN = 5;
const RESTART_BACKOFF_MS = [250, 500, 1000, 2000, 4000];
// 握手专用，不占用调用方的 id 序列（从 1 起）。
const HANDSHAKE_ID = 0;

const REPO_ROOT = path.join(__dirname, '..', '..');
const FRONTEND_ROOT = path.join(__dirname, '..');
const CONFIG_PATH = path.join(FRONTEND_ROOT, 'sidecar.config.json');

class Sidecar extends EventEmitter {
  constructor(options = {}) {
    super();
    // 真实后端优先：配置了 Python 解释器就用 sprite_workshop.daemon，
    // 否则回落到 Node 版 mock，让界面在没有 Python 的机器上仍能开发。
    const backend = options.backend ?? Sidecar.resolveBackend();
    this.command = options.command ?? backend.command;
    this.args = options.args ?? backend.args;
    this.cwd = options.cwd ?? backend.cwd;
    this.kind = backend.kind;

    this.child = null;
    this.pending = new Map();
    this.nextId = 1;
    this.restarts = 0;
    this.stopping = false;
    this.status = 'stopped';

    // 在 Electron 主进程里 process.execPath 是 electron.exe，不是 node。
    // 直接拿它跑 .mjs 会被当成一个 Electron 应用启动，进程随即退出。
    // 用官方开关让 electron.exe 以纯 Node 模式运行。
    // 换成真实 Python 后端时 command 不再是 execPath，这个开关自然不生效。
    this.runAsNode = options.runAsNode ?? this.command === process.execPath;
    // 中文项目名走 stdio 时，Windows 默认代码页会把它烧成乱码。
    this.extraEnv = this.kind === 'python' ? { PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } : {};
  }

  /**
   * 解析后端来源，优先级：环境变量 > sidecar.config.json > Node mock。
   * 不打包 Python 解释器是 FRONTEND_PLAN.md §9.2 的明确取舍，
   * 所以解释器路径属于本机配置，不进项目也不进仓库。
   */
  static resolveBackend() {
    // 保留显式 mock 开关，供纯前端开发和离线契约测试使用；正常启动
    // 始终优先真实 Python 后端。
    const forceMock = process.env.SPRITE_WORKSHOP_FORCE_MOCK === '1';
    const python = forceMock
      ? null
      : process.env.SPRITE_WORKSHOP_PYTHON || Sidecar._configuredPython();

    if (python && fs.existsSync(python)) {
      return {
        kind: 'python',
        command: python,
        args: ['-m', 'sprite_workshop.daemon', '--stdio'],
        cwd: REPO_ROOT,
      };
    }

    return {
      kind: 'mock',
      command: process.execPath,
      args: [path.join(FRONTEND_ROOT, 'mock', 'mock-sidecar.mjs')],
      cwd: FRONTEND_ROOT,
    };
  }

  static _configuredPython() {
    try {
      return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')).python ?? null;
    } catch {
      return null;
    }
  }

  start() {
    if (this.child) return;
    this.stopping = false;
    this._setStatus('starting');

    const env = { ...process.env, ...this.extraEnv };
    if (this.runAsNode) env.ELECTRON_RUN_AS_NODE = '1';
    this.emit('log', `backend=${this.kind} ${this.command}`);

    const child = spawn(this.command, this.args, {
      cwd: this.cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.child = child;

    createInterface({ input: child.stdout }).on('line', (line) => this._onLine(line));
    createInterface({ input: child.stderr }).on('line', (line) => {
      this.emit('log', line);
    });

    child.on('error', (error) => {
      this.emit('log', `spawn failed: ${error.message}`);
      this._teardown(`无法启动后端进程：${error.message}`);
    });
    child.on('exit', (code, signal) => {
      if (this.stopping) return;
      this._teardown(`后端进程退出（code=${code} signal=${signal}）`);
      this._scheduleRestart();
    });

    // spawn 成功 ≠ 后端可用。Python 侧 import 失败时进程照样起得来，
    // 之前这里直接报 ready，界面会一直显示后端健康，直到第一个请求 30s 超时。
    // 用一次 app.hello 握手来定义就绪。
    // 注意：restarts 不在这里重置。只有真正收到过一次成功响应才算启动成功，
    // 否则「spawn 成功但立刻退出」会把退避重置成常数重试，变成刷屏死循环。
    // 用保留 id 0，让调用方看到的 id 序列仍然从 1 开始 —— 握手不该改变
    // 外部可观察的编号，否则任何按 id 取消的调用方都会取消错请求。
    this.call('app.hello', {}, { timeoutMs: 10000, id: HANDSHAKE_ID }).then(
      () => {
        if (this.child === child) this._setStatus('ready');
      },
      (error) => {
        if (this.child === child) this._setStatus('down', error.message);
      },
    );
  }

  stop() {
    this.stopping = true;
    if (this.child) {
      // 先让在飞请求以「后端不可用」失败，否则它们会一直挂到 30s 超时，
      // 而 sidecar:restart 会在每次重启时留下一批这样的悬挂 promise。
      this._rejectPending('后端已停止');
      this.child.stdin.end();
      this.child.kill();
      this.child = null;
    }
    this._setStatus('stopped');
  }

  call(method, params, { timeoutMs = 30000, id: forcedId = null } = {}) {
    if (!this.child) {
      return Promise.reject(
        Object.assign(new Error('后端未运行'), {
          rpc: { code: ERR_BACKEND_DOWN, message: '后端未运行', details: null },
        }),
      );
    }
    let id;
    if (forcedId === null) {
      id = this.nextId;
      this.nextId += 1;
    } else {
      id = forcedId;
    }

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          Object.assign(new Error('后端响应超时'), {
            rpc: { code: ERR_BACKEND_DOWN, message: '后端响应超时', details: { method } },
          }),
        );
      }, timeoutMs);

      this.pending.set(id, { resolve, reject, timer, method });
      this.child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }

  cancel(requestId) {
    if (!this.child) return;
    this.child.stdin.write(`${JSON.stringify({ method: '$cancel', params: { request: requestId } })}\n`);
  }

  _onLine(line) {
    const text = line.trim();
    if (!text) return;

    let msg;
    try {
      msg = JSON.parse(text);
    } catch {
      // 契约要求 stdout 只有 JSON；出现杂质说明后端违约，记下来但不崩。
      this.emit('log', `协议违约，stdout 出现非 JSON：${text.slice(0, 120)}`);
      return;
    }

    if (msg.id === undefined) {
      // 通知（进度等）
      this.emit('notification', msg);
      return;
    }

    const entry = this.pending.get(msg.id);
    if (!entry) return; // 迟到的响应直接丢弃
    this.pending.delete(msg.id);
    clearTimeout(entry.timer);

    if (msg.ok) {
      // 收到成功响应才算真的起来了，可以把退避计数清零。
      this.restarts = 0;
      entry.resolve(msg);
    } else {
      const rpc = msg.error ?? { code: 4, message: '未知错误', details: null };
      entry.reject(Object.assign(new Error(rpc.message), { rpc, envelope: msg }));
    }
  }

  _rejectPending(reason) {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(
        Object.assign(new Error(reason), {
          rpc: { code: ERR_BACKEND_DOWN, message: reason, details: null },
        }),
      );
    }
    this.pending.clear();
  }

  _teardown(reason) {
    this.child = null;
    this._rejectPending(reason);
    this._setStatus('down', reason);
  }

  _scheduleRestart() {
    const delay = RESTART_BACKOFF_MS[Math.min(this.restarts, RESTART_BACKOFF_MS.length - 1)];
    this.restarts += 1;
    this.emit('log', `${delay}ms 后重启后端（第 ${this.restarts} 次）`);
    setTimeout(() => {
      if (!this.stopping) this.start();
    }, delay);
  }

  _setStatus(status, detail = null) {
    this.status = status;
    this.emit('status', { status, detail });
  }
}

module.exports = { Sidecar };
