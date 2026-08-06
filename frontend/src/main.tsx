import React, { ErrorInfo, ReactNode, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

interface ErrorBoundaryState {
  error: Error | null;
}

class ErrorBoundary extends React.Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };
  private readonly childContent: ReactNode;

  constructor(props: { children: ReactNode }) {
    super(props);
    this.childContent = props.children;
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ClaimCourt render error', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="min-h-screen bg-[#0d0f14] p-8 font-mono text-gray-200">
          <div className="mx-auto max-w-2xl border border-red-800 bg-[#141720] p-6">
            <div className="mb-2 text-xs font-bold tracking-widest text-red-400">CLAIMCOURT UI ERROR</div>
            <h1 className="mb-4 text-lg font-bold text-gray-100">The local interface stopped rendering.</h1>
            <pre className="mb-6 overflow-auto whitespace-pre-wrap border border-gray-800 bg-[#0f121a] p-3 text-xs text-red-200">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="border border-emerald-700 px-4 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-950"
            >
              RELOAD LOCAL UI
            </button>
          </div>
        </main>
      );
    }
    return this.childContent;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
