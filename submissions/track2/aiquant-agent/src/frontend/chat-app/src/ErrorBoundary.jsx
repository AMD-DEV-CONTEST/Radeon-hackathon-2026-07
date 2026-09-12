import React from 'react';

/**
 * 全局错误边界：防止 JS 运行时错误导致白屏。
 * 捕获子组件树渲染错误，显示友好错误提示。
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('[aiQuant] 渲染错误:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return React.createElement('div', {
        style: {
          padding: '40px', textAlign: 'center', color: '#e4e8f0',
          background: '#0b0e14', height: '100%', display: 'flex',
          flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        }
      }, [
        React.createElement('div', { key: 'icon', style: { fontSize: '48px', marginBottom: '16px' } }, '⚠️'),
        React.createElement('h2', { key: 'title', style: { color: '#ef4444', marginBottom: '8px' } }, '渲染出错'),
        React.createElement('p', { key: 'msg', style: { color: '#8794a8', maxWidth: '400px', fontSize: '14px' } },
          this.state.error?.message || '未知错误'),
        React.createElement('button', {
          key: 'btn',
          onClick: () => { this.setState({ hasError: false, error: null }); window.location.reload(); },
          style: {
            marginTop: '16px', padding: '8px 20px', background: '#3b82f6', color: '#fff',
            border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '14px',
          }
        }, '刷新页面'),
      ]);
    }
    return this.props.children;
  }
}
