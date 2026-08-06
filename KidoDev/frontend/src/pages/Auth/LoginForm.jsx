import React from 'react';

export function LoginForm({ email, setEmail, password, setPassword }) {
    return (
        <>
            <div className="col-12">
                <label className="form-label fw-bold small text-primary">Email or CNIC</label>
                <input
                    type="text"
                    className="form-control rounded-pill px-4 shadow-sm border-primary border-opacity-25"
                    placeholder="Email or CNIC (No Dashes)"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                />
            </div>
            <div className="col-12">
                <label className="form-label fw-bold small text-primary">Password</label>
                <input
                    type="password"
                    className="form-control rounded-pill px-4 shadow-sm border-primary border-opacity-25"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                />
            </div>
            <p className="text-muted small mt-2 px-3 text-center" style={{ fontSize: '0.75rem' }}>
                Tip: Your initial password is your CNIC number (no dashes).
            </p>
        </>
    );
}
