"use client";

import React, { Component, ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackMessage?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Global React Error Boundary.
 * Catches unhandled rendering exceptions in the component tree and
 * displays a recovery UI instead of crashing the entire application
 * to a white screen of death.
 */
export class DeterminexErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    // Log to console for debugging — could also push to Matrix terminal via API
    console.error("[DETERMINEX_ERROR_BOUNDARY] Unhandled React error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full w-full bg-[#0a0a0a] text-gray-300 p-8 gap-4 font-mono">
          <div className="border border-red-900/50 bg-red-950/20 rounded-lg p-6 max-w-xl w-full shadow-lg shadow-red-900/10">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-red-400 text-lg">⚠</span>
              <h2 className="text-red-400 font-bold text-sm uppercase tracking-widest">
                Immune System Intercepted a UI Crash
              </h2>
            </div>
            <p className="text-xs text-gray-400 mb-3">
              {this.props.fallbackMessage ||
                "A component in the Determinex UI tree threw an unrecoverable error. The application has been isolated to prevent a full white-screen crash."}
            </p>
            <pre className="text-label text-red-300/70 bg-black/40 rounded p-3 overflow-auto max-h-40 mb-4 border border-red-900/30">
              {this.state.error?.toString()}
              {this.state.errorInfo?.componentStack?.slice(0, 500)}
            </pre>
            <button
              onClick={this.handleReset}
              className="px-4 py-1.5 bg-red-900/40 hover:bg-red-900/60 border border-red-800/50 rounded text-xs text-red-300 transition-colors cursor-pointer"
            >
              Attempt Recovery
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
