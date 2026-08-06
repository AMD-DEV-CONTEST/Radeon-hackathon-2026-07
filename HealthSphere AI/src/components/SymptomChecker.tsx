import React, { useState, useEffect } from "react";
import { analyzeSymptoms } from "../data";
import { saveSymptomCheck, getSymptomChecks } from "../lib/firebase";
import { SymptomCheckResult } from "../types";
import { AlertTriangle, CheckSquare, Square, HeartPulse, History, AlertCircle, RefreshCw, Activity } from "lucide-react";
import { motion } from "motion/react";

interface SymptomCheckerProps {
  user: any;
  isGuest: boolean;
}

const AVAILABLE_SYMPTOMS = [
  { key: "fever", label: "High Fever & Chills", desc: "Body temperature above 100.4°F (38°C)" },
  { key: "cough", label: "Persistent Dry/Wet Cough", desc: "Irritating bronchial cough or phlegm" },
  { key: "headache", label: "Severe Headache", desc: "Intense pressure, or pain behind the eyes" },
  { key: "shortness_of_breath", label: "Shortness of Breath", desc: "Difficulty breathing, gasping, or tight lungs" },
  { key: "joint_pain", label: "Severe Joint & Muscle Pain", desc: "Aching bones, joints, or severe body soreness" },
  { key: "high_blood_sugar", label: "High Blood Sugar (Glucose)", desc: "Elevated readings, constant thirst, frequent urination" },
  { key: "chest_pain", label: "Chest Pain / Tightness", desc: "CRITICAL: Pain, pressure, or squeeze in the heart area" },
  { key: "wheezing", label: "Wheezing / Whistling Breath", desc: "High-pitched whistling sound during exhalation" }
];

export default function SymptomChecker({ user, isGuest }: SymptomCheckerProps) {
  const [selectedSymptoms, setSelectedSymptoms] = useState<string[]>([]);
  const [result, setResult] = useState<any | null>(null);
  const [history, setHistory] = useState<SymptomCheckResult[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    if (user) {
      loadHistory();
    }
  }, [user]);

  const loadHistory = async () => {
    setLoadingHistory(true);
    try {
      const data = await getSymptomChecks(user.uid);
      setHistory(data);
    } catch (err) {
      console.error("Error loading symptom check history:", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleToggleSymptom = (key: string) => {
    setSelectedSymptoms((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]
    );
  };

  const handleAnalyze = async () => {
    if (selectedSymptoms.length === 0) return;
    setAnalyzing(true);

    setTimeout(async () => {
      const triage = analyzeSymptoms(selectedSymptoms);
      const output = {
        symptoms: selectedSymptoms.map(key => AVAILABLE_SYMPTOMS.find(s => s.key === key)?.label || key),
        conditions: triage.conditions,
        riskLevel: triage.riskLevel,
        advice: triage.advice,
        createdAt: new Date()
      };

      setResult(output);

      // Save to Firebase if logged in
      if (user) {
        try {
          await saveSymptomCheck(user.uid, selectedSymptoms, triage.conditions, triage.riskLevel);
          loadHistory(); // reload history list
        } catch (err) {
          console.error("Error saving symptom check to database:", err);
        }
      }
      setAnalyzing(false);
    }, 800);
  };

  const handleReset = () => {
    setSelectedSymptoms([]);
    setResult(null);
  };

  const getRiskColor = (level: string) => {
    switch (level) {
      case "High":
        return "bg-rose-50 border-rose-100 text-rose-700";
      case "Moderate":
        return "bg-amber-50 border-amber-100 text-amber-700";
      default:
        return "bg-emerald-50 border-emerald-100 text-emerald-700";
    }
  };

  const getRiskBadge = (level: string) => {
    switch (level) {
      case "High":
        return "bg-rose-600 text-white shadow-rose-500/20";
      case "Moderate":
        return "bg-amber-500 text-white shadow-amber-500/20";
      default:
        return "bg-emerald-500 text-white shadow-emerald-500/20";
    }
  };

  return (
    <div id="symptom-checker-view" className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      
      {/* Left 2 Columns: Symptom Selector and Analysis */}
      <div className="lg:col-span-2 space-y-6">
        
        {/* Intro */}
        <div className="bg-white p-6 border border-slate-100 rounded-2xl shadow-sm">
          <h2 id="symptom-checker-h2" className="text-2xl font-sans font-bold tracking-tight text-slate-900">
            Intelligent Symptom Triage Checker
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            Check your symptoms and receive instant public health advisory recommendations.
          </p>

          {/* Core Critical Alert */}
          <div className="mt-4 p-4 bg-rose-50 border border-rose-100 text-rose-800 rounded-xl flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              <span className="font-bold uppercase tracking-wider block text-rose-900">Critical Emergency Warning</span>
              <p className="leading-relaxed font-normal">
                If you are experiencing severe crushing chest pain, extreme dyspnea (shortness of breath), sudden severe slurred speech or numbness, please do not use this applet. Call emergency services <span className="font-bold">112 / 911</span> immediately or visit the nearest trauma room.
              </p>
            </div>
          </div>
        </div>

        {/* Checker Grid */}
        {!result ? (
          <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm space-y-6">
            <div>
              <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Step 1: Symptom Checklist</span>
              <h3 className="text-base font-sans font-bold text-slate-900 mt-0.5">Select all symptoms currently being experienced</h3>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {AVAILABLE_SYMPTOMS.map((symptom) => {
                const isChecked = selectedSymptoms.includes(symptom.key);
                return (
                  <div
                    id={`symptom-card-${symptom.key}`}
                    key={symptom.key}
                    onClick={() => handleToggleSymptom(symptom.key)}
                    className={`p-4 rounded-xl border text-left cursor-pointer select-none transition-all duration-200 flex items-start gap-3 ${
                      isChecked
                        ? "bg-blue-50/50 border-blue-400 shadow-sm"
                        : "bg-slate-50/50 border-slate-200/70 hover:border-slate-300"
                    }`}
                  >
                    <div className="mt-0.5 shrink-0">
                      {isChecked ? (
                        <div className="w-4 h-4 bg-blue-600 rounded flex items-center justify-center text-white">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                          </svg>
                        </div>
                      ) : (
                        <div className="w-4 h-4 border border-slate-300 bg-white rounded" />
                      )}
                    </div>
                    <div>
                      <span className="text-sm font-bold text-slate-800 block leading-tight">
                        {symptom.label}
                      </span>
                      <span className="text-[11px] text-slate-400 font-normal leading-relaxed block mt-0.5">
                        {symptom.desc}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="pt-4 border-t border-slate-50 flex items-center justify-between">
              <span className="text-xs text-slate-400">
                Selected: {selectedSymptoms.length} symptom{selectedSymptoms.length !== 1 && "s"}
              </span>
              <button
                id="btn-run-analysis"
                onClick={handleAnalyze}
                disabled={selectedSymptoms.length === 0 || analyzing}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none text-white font-semibold text-sm rounded-xl shadow-md shadow-blue-500/10 flex items-center gap-2 transition-all cursor-pointer"
              >
                {analyzing ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Analyzing...</span>
                  </>
                ) : (
                  <>
                    <Activity className="w-4 h-4" />
                    <span>Analyze Symptoms</span>
                  </>
                )}
              </button>
            </div>
          </div>
        ) : (
          /* Analysis Results Panel */
          <motion.div
            id="symptom-results-panel"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm space-y-6"
          >
            <div className="flex items-center justify-between border-b border-slate-50 pb-4">
              <div>
                <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Triage Analysis Complete</span>
                <h3 className="text-lg font-sans font-bold text-slate-900">Primary Health Assessment</h3>
              </div>
              <button
                id="btn-retest-symptoms"
                onClick={handleReset}
                className="px-4 py-2 border border-slate-200 hover:bg-slate-50 text-xs font-bold text-slate-600 rounded-xl transition cursor-pointer"
              >
                Run New Checker
              </button>
            </div>

            {/* Selected Symptoms list */}
            <div className="space-y-2 bg-slate-50 border border-slate-100 p-4 rounded-xl">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block">Symptoms Evaluated</span>
              <div className="flex flex-wrap gap-1.5">
                {result.symptoms.map((symp: string, i: number) => (
                  <span key={i} className="px-2.5 py-1 bg-white text-slate-700 text-xs font-medium rounded-lg border border-slate-200">
                    {symp}
                  </span>
                ))}
              </div>
            </div>

            {/* Condition matches and risk level */}
            <div className={`p-5 rounded-2xl border ${getRiskColor(result.riskLevel)} space-y-4`}>
              <div className="flex items-start justify-between">
                <div>
                  <span className="text-[10px] font-bold uppercase tracking-wider block opacity-70">Calculated Advisory Severity</span>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${getRiskBadge(result.riskLevel)}`}>
                      {result.riskLevel} Risk
                    </span>
                  </div>
                </div>
                
                <div className="text-right">
                  <span className="text-[10px] font-bold uppercase tracking-wider block opacity-70">Postulated Conditions</span>
                  <span className="text-sm font-bold text-slate-900 block mt-1">
                    {result.conditions.join(" / ")}
                  </span>
                </div>
              </div>

              <div className="border-t border-slate-900/10 pt-4 space-y-2">
                <span className="text-xs font-bold uppercase tracking-widest flex items-center gap-1.5">
                  <AlertCircle className="w-4.5 h-4.5" />
                  <span>Clinical Advisor Recommendations</span>
                </span>
                <p className="text-xs leading-relaxed font-normal opacity-90">
                  {result.advice}
                </p>
              </div>
            </div>

            {/* Medical disclaimer note */}
            <div className="text-[11px] text-slate-400 leading-relaxed bg-slate-50 p-4 border border-slate-100 rounded-xl">
              <span className="font-bold text-slate-600 uppercase tracking-widest block mb-1">Standard Medical Disclaimer</span>
              This output is purely educational and compiled by automated rules. It is not an official medical diagnostic report, doctor consultation, or prescription. Always verify symptoms with a licensed general practitioner (GP) or clinical specialist.
            </div>

          </motion.div>
        )}

      </div>

      {/* Right Column: Historical Reports (Auth Only) */}
      <div className="space-y-6">
        <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm">
          <div className="flex items-center gap-2 border-b border-slate-50 pb-4 mb-4">
            <History className="w-4.5 h-4.5 text-blue-600" />
            <h3 className="font-sans font-bold text-sm text-slate-900 uppercase tracking-wider">
              Your Check History
            </h3>
          </div>

          {isGuest ? (
            <div className="text-center py-8 bg-slate-50 border border-slate-100 rounded-xl px-4 space-y-3">
              <AlertCircle className="w-8 h-8 text-amber-500 mx-auto" />
              <div>
                <span className="text-xs font-bold text-slate-800 block">History is Disabled</span>
                <span className="text-[11px] text-slate-400 block mt-1">
                  Create a professional HealthSphere AI profile to save your historical symptom checkers and sync medical reports.
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-3 max-h-[450px] overflow-y-auto pr-1">
              {loadingHistory ? (
                <div className="text-center py-8">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto text-blue-500" />
                  <span className="text-xs text-slate-400 mt-2 block font-medium">Retrieving archives...</span>
                </div>
              ) : history.length === 0 ? (
                <div className="text-center py-10 bg-slate-50 border border-slate-100 rounded-xl text-slate-400">
                  <span className="text-xs font-semibold block">No historical records</span>
                  <span className="text-[10px] text-slate-500 mt-0.5 block">Run an analysis to save it.</span>
                </div>
              ) : (
                history.map((record) => (
                  <div
                    key={record.id}
                    className="p-3 border border-slate-100 hover:border-slate-200 bg-slate-50/50 rounded-xl transition-all"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-400 font-mono">
                        {record.createdAt?.toDate ? record.createdAt.toDate().toLocaleDateString() : new Date(record.createdAt).toLocaleDateString()}
                      </span>
                      <span className={`px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded border ${
                        record.riskLevel === "High"
                          ? "bg-rose-50 border-rose-100 text-rose-700"
                          : record.riskLevel === "Moderate"
                          ? "bg-amber-50 border-amber-100 text-amber-700"
                          : "bg-emerald-50 border-emerald-100 text-emerald-700"
                      }`}>
                        {record.riskLevel}
                      </span>
                    </div>

                    <div className="mt-2 space-y-1">
                      <span className="text-xs font-bold text-slate-800 block">
                        {record.conditions.join(" / ")}
                      </span>
                      
                      {/* Symptoms list mini preview */}
                      <div className="flex flex-wrap gap-1 mt-1">
                        {record.symptoms.map((sym, index) => (
                          <span key={index} className="text-[9px] font-medium bg-white text-slate-500 border border-slate-100 px-1 py-0.5 rounded">
                            {sym.replace(/(\(.*?\))/g, "").trim()}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
