import React from 'react';

export const SignupForm = ({ parentName, setParentName, email, setEmail, password, setPassword }) => {
    return (
        <>
            <div className="col-12">
                <div className="form-floating mb-3">
                    <input
                        type="text"
                        className="form-control rounded-pill px-4"
                        id="parentName"
                        placeholder="John Doe"
                        value={parentName}
                        onChange={(e) => setParentName(e.target.value)}
                        required
                    />
                    <label htmlFor="parentName" className="px-4">Parent's Full Name</label>
                </div>
            </div>

            <div className="col-12">
                <div className="form-floating mb-3">
                    <input
                        type="email"
                        className="form-control rounded-pill px-4"
                        id="signupEmail"
                        placeholder="name@example.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                    />
                    <label htmlFor="signupEmail" className="px-4">Your Email Address</label>
                </div>
            </div>

            <div className="col-12">
                <div className="form-floating">
                    <input
                        type="password"
                        className="form-control rounded-pill px-4"
                        id="signupPassword"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        minLength={6}
                    />
                    <label htmlFor="signupPassword" className="px-4">Create Password</label>
                </div>
            </div>
            
            <p className="text-muted small mt-3 px-3 text-center">
                Register your school to start managing your student's learning path.
            </p>
        </>
    );
};
