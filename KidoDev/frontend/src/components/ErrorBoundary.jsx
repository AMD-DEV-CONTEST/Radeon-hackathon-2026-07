import React from 'react';

/**
 * ErrorBoundary — catches any render or lifecycle crash in children.
 * Shows a friendly recovery UI instead of a blank page.
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
        console.error('[ErrorBoundary] Caught error:', error, info.componentStack);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center',
                    justifyContent: 'center', height: '100vh',
                    background: 'linear-gradient(135deg,#1e1b4b,#312e81)',
                    fontFamily: 'Inter,sans-serif', color: '#fff', padding: 32,
                }}>
                    <div style={{ fontSize: 64, marginBottom: 16 }}>😿</div>
                    <h2 style={{ fontSize: 28, fontWeight: 800, marginBottom: 8 }}>
                        Oops! Something went wrong
                    </h2>
                    <p style={{ color: '#A5B4FC', fontSize: 15, marginBottom: 32, textAlign: 'center', maxWidth: 420 }}>
                        The studio hit a snag. This is usually fixed by a quick reload.
                    </p>
                    <div style={{ display: 'flex', gap: 12 }}>
                        <button
                            onClick={() => window.location.reload()}
                            style={{
                                background: '#6366F1', color: '#fff', border: 'none',
                                borderRadius: 12, padding: '12px 28px', fontSize: 15,
                                fontWeight: 700, cursor: 'pointer',
                            }}
                        >
                            🔄 Reload Studio
                        </button>
                        <button
                            onClick={() => window.history.back()}
                            style={{
                                background: 'rgba(255,255,255,0.12)', color: '#fff', border: 'none',
                                borderRadius: 12, padding: '12px 28px', fontSize: 15,
                                fontWeight: 700, cursor: 'pointer',
                            }}
                        >
                            ← Go Back
                        </button>
                    </div>
                    {process.env.NODE_ENV === 'development' && this.state.error && (
                        <details style={{ marginTop: 24, maxWidth: 600, width: '100%' }}>
                            <summary style={{ cursor: 'pointer', color: '#818CF8', fontSize: 13 }}>
                                Error details (dev only)
                            </summary>
                            <pre style={{
                                background: 'rgba(0,0,0,0.4)', padding: 14, borderRadius: 8,
                                fontSize: 11, color: '#FCA5A5', overflow: 'auto', marginTop: 8,
                            }}>
                                {this.state.error.toString()}
                            </pre>
                        </details>
                    )}
                </div>
            );
        }
        return this.props.children;
    }
}
