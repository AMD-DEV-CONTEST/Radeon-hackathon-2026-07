import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import { FiCheckCircle, FiAlertTriangle, FiAward, FiGlobe } from 'react-icons/fi';

const VerifyCertificate = () => {
  const { code } = useParams();
  const [loading, setLoading] = useState(true);
  const [cert, setCert] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const verify = async () => {
      try {
        const res = await axios.get(`/api/auth/certificate/verify/${code}`);
        setCert(res.data);
      } catch (err) {
        setError(err.response?.data?.message || 'Certificate verification failed.');
      } finally {
        setLoading(false);
      }
    };
    verify();
  }, [code]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-white">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-t-primary-500 border-slate-800"></div>
        <p className="mt-4 text-xs text-gray-400">Verifying credential status...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-6 text-white font-sans">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl text-center space-y-6 relative overflow-hidden">
        <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-green-500 to-emerald-500"></div>
        
        {error ? (
          <>
            <div className="mx-auto h-16 w-16 rounded-2xl bg-red-500/10 text-red-500 flex items-center justify-center border border-red-500/20">
              <FiAlertTriangle className="h-8 w-8" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-red-500">Invalid Credential</h2>
              <p className="text-xs text-gray-400 mt-2">This verification code does not match any registered certificate.</p>
            </div>
            <div className="p-3 bg-red-500/5 border border-red-500/10 rounded-xl text-xs text-red-450 font-mono">
              Code: {code}
            </div>
          </>
        ) : (
          <>
            <div className="mx-auto h-16 w-16 rounded-2xl bg-green-500/10 text-green-500 flex items-center justify-center border border-green-500/20 animate-pulse">
              <FiCheckCircle className="h-8 w-8" />
            </div>
            <div>
              <span className="inline-flex items-center gap-1 text-[10px] font-bold text-green-500 bg-green-500/10 px-2.5 py-0.5 rounded-full border border-green-500/20 uppercase tracking-widest">
                Verified Credential
              </span>
              <h2 className="text-xl font-black mt-3 text-slate-100">Verified Diploma</h2>
            </div>

            <div className="space-y-4 text-left border-t border-b border-slate-800/80 py-4 my-2 text-xs">
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wide">Recipient Name</p>
                <p className="text-sm font-bold text-slate-100 mt-0.5 capitalize">{cert.recipientName}</p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wide">Course Completed</p>
                <p className="text-sm font-bold text-slate-100 mt-0.5">{cert.courseName}</p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wide">Completion Date</p>
                <p className="text-sm font-bold text-slate-100 mt-0.5">
                  {new Date(cert.issueDate).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wide">Verification ID</p>
                <p className="text-sm font-mono font-bold text-primary-400 mt-0.5">{cert.verificationCode}</p>
              </div>
            </div>
          </>
        )}

        <div className="pt-2">
          <Link
            to="/login"
            className="inline-flex items-center gap-2 text-xs font-bold text-slate-400 hover:text-white transition"
          >
            <FiGlobe /> Go to LinguaBot Login
          </Link>
        </div>
      </div>
    </div>
  );
};

export default VerifyCertificate;
