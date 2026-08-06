import React from 'react';

export const KidLoginForm = ({ secretKey, setSecretKey }) => {
    return (
        <div className="col-12">
            <div className="form-floating mb-3">
                <input
                    type="text"
                    className="form-control rounded-pill px-4"
                    id="secretKey"
                    placeholder="ABC12345"
                    value={secretKey}
                    onChange={(e) => setSecretKey(e.target.value.toUpperCase())}
                    required
                />
                <label htmlFor="secretKey" className="px-4">Your Secret Key (e.g. ABC26026)</label>
            </div>
            <p className="text-muted small text-center px-3">
                Don't know your key? Ask your parent to give it to you!
            </p>
        </div>
    );
};
