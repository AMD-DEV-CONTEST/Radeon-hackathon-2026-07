import React from 'react';
import { createRoot } from 'react-dom/client';
import ChatPanel from './App';
import ErrorBoundary from './ErrorBoundary';
import './index.css';

// 挂载到指定容器（防重复挂载）
window.mountAiquantChat = function (containerId) {
  const container = document.getElementById(containerId || 'aiquant-chat-root');
  if (!container) {
    console.error('[aiQuant Chat] container not found:', containerId);
    return;
  }
  if (window._aiquantChatRoot) {
    console.warn('[aiQuant Chat] already mounted, skipping');
    return;
  }
  const root = createRoot(container);
  root.render(
    React.createElement(ErrorBoundary, null,
      React.createElement(ChatPanel)
    )
  );
  window._aiquantChatRoot = root;
};

// 卸载
window.unmountAiquantChat = function () {
  if (window._aiquantChatRoot) {
    window._aiquantChatRoot.unmount();
    delete window._aiquantChatRoot;
  }
};

// 自动挂载（如果存在 #aiquant-chat-root）
const autoMountEl = document.getElementById('aiquant-chat-root');
if (autoMountEl) {
  window.mountAiquantChat('aiquant-chat-root');
}
