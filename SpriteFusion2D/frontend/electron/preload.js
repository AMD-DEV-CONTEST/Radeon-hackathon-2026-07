'use strict';
// 渲染进程能看到的全部能力就是下面这些。
// 没有 fs、没有 child_process、没有 path —— FRONTEND_PLAN.md §9.1。

const { contextBridge, ipcRenderer } = require('electron');

const listeners = { status: [], log: [], notification: [] };

ipcRenderer.on('sidecar:status', (_e, payload) => listeners.status.forEach((f) => f(payload)));
ipcRenderer.on('sidecar:log', (_e, line) => listeners.log.forEach((f) => f(line)));
ipcRenderer.on('sidecar:notification', (_e, msg) =>
  listeners.notification.forEach((f) => f(msg)),
);

contextBridge.exposeInMainWorld('workshop', {
  call: (method, params) => ipcRenderer.invoke('rpc:call', { method, params }),
  cancel: (requestId) => ipcRenderer.invoke('rpc:cancel', requestId),
  restartSidecar: () => ipcRenderer.invoke('sidecar:restart'),
  openProjectDialog: () => ipcRenderer.invoke('dialog:openProject'),
  openFileDialog: (options) => ipcRenderer.invoke('dialog:openFile', options),
  newProjectDirDialog: () => ipcRenderer.invoke('dialog:newProjectDir'),
  importImageDialog: () => ipcRenderer.invoke('dialog:importImage'),
  exportDirDialog: () => ipcRenderer.invoke('dialog:exportDir'),
  defaultProject: () => ipcRenderer.invoke('app:defaultProject'),
  on: (channel, handler) => {
    if (!listeners[channel]) throw new Error(`未知频道：${channel}`);
    listeners[channel].push(handler);
  },
});
