import React, { useState } from "react";
import { DISEASE_LIBRARY } from "../data";
import { DiseaseInfo } from "../types";
import { Search, Info, Shield, HelpCircle, ArrowUpRight, CheckCircle2, ChevronRight, X } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export default function DiseaseLibrary() {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [activeModalDisease, setActiveModalDisease] = useState<DiseaseInfo | null>(null);

  const categories = ["All", "Vector-borne Viral Infection", "Respiratory Viral Infection", "Metabolic/Chronic Disease", "Cardiovascular/Chronic Condition", "Chronic Respiratory Disease"];

  const filteredDiseases = DISEASE_LIBRARY.filter((disease) => {
    const matchesSearch = disease.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          disease.category.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          disease.overview.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesCategory = selectedCategory === "All" || disease.category === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  const getSeverityStyle = (severity: string) => {
    switch (severity) {
      case "High":
        return "bg-rose-50 text-rose-700 border-rose-100";
      case "Medium":
        return "bg-amber-50 text-amber-700 border-amber-100";
      default:
        return "bg-emerald-50 text-emerald-700 border-emerald-100";
    }
  };

  return (
    <div id="disease-library-view" className="space-y-8">
      
      {/* Header and Search Area */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-6 border border-slate-100 rounded-2xl shadow-sm">
        <div className="space-y-1">
          <h2 id="library-title-h2" className="text-2xl font-sans font-bold tracking-tight text-slate-900">
            Clinical Disease Library
          </h2>
          <p className="text-sm text-slate-500">
            Access official public health descriptions, symptoms, prevention checklists, and causes.
          </p>
        </div>

        {/* Search input */}
        <div className="relative w-full md:w-80">
          <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
            <Search className="w-4 h-4" />
          </span>
          <input
            id="disease-search-input"
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 focus:border-blue-500 focus:bg-white rounded-xl text-sm font-medium transition-all outline-none placeholder:text-slate-400 text-slate-800"
            placeholder="Search symptoms or conditions..."
          />
        </div>
      </div>

      {/* Category filters */}
      <div id="category-filter-rail" className="flex items-center gap-1.5 overflow-x-auto pb-2 scrollbar-none">
        {categories.map((cat) => (
          <button
            id={`category-pill-${cat.replace(/\s+/g, "-")}`}
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all border ${
              selectedCategory === cat
                ? "bg-blue-600 border-blue-600 text-white shadow-md shadow-blue-500/10"
                : "bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-800"
            }`}
          >
            {cat === "All" ? "All Conditions" : cat.split("/")[0]}
          </button>
        ))}
      </div>

      {/* Diseases Grid */}
      <div id="diseases-grid" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredDiseases.map((disease) => (
          <motion.div
            id={`disease-card-${disease.id}`}
            key={disease.id}
            layout
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm hover:shadow-md hover:border-blue-100 transition-all duration-300 flex flex-col justify-between"
          >
            <div className="space-y-4">
              {/* Card Header */}
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-[10px] font-mono tracking-wider text-blue-600 uppercase font-bold">
                    {disease.category}
                  </span>
                  <h3 className="text-lg font-sans font-bold text-slate-900 mt-0.5">
                    {disease.name}
                  </h3>
                </div>
                <span className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-full border ${getSeverityStyle(disease.severity)}`}>
                  {disease.severity} Severity
                </span>
              </div>

              {/* Card Body */}
              <p className="text-xs text-slate-500 leading-relaxed line-clamp-3">
                {disease.overview}
              </p>

              {/* Quick Preview list */}
              <div className="space-y-2 border-t border-slate-50 pt-3">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block">Core Symptoms</span>
                <div className="flex flex-wrap gap-1.5">
                  {disease.symptoms.slice(0, 3).map((symp, i) => (
                    <span key={i} className="px-2 py-1 bg-slate-50 text-slate-600 text-[10px] font-medium rounded-md border border-slate-100 max-w-[150px] truncate">
                      {symp.replace(/(\(.*?\))/g, "").trim()}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Card Footer */}
            <div className="pt-6 mt-4 border-t border-slate-50 flex items-center justify-between">
              <span className="text-[11px] font-mono text-slate-400">
                HealthSphere Library
              </span>
              <button
                id={`btn-explore-${disease.id}`}
                onClick={() => setActiveModalDisease(disease)}
                className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 hover:text-blue-700 uppercase tracking-wider cursor-pointer group"
              >
                <span>Explore Details</span>
                <ArrowUpRight className="w-3.5 h-3.5 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>
          </motion.div>
        ))}

        {filteredDiseases.length === 0 && (
          <div className="col-span-full py-16 text-center bg-white border border-slate-100 rounded-2xl shadow-sm">
            <span className="text-sm font-semibold text-slate-400 block">No clinical records found</span>
            <span className="text-xs text-slate-500 mt-1 block">Try adjusting your search keywords or filter category.</span>
          </div>
        )}
      </div>

      {/* Disease Detail Modal */}
      <AnimatePresence>
        {activeModalDisease && (
          <div id="disease-modal-overlay" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div
              id="disease-modal-content"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="relative w-full max-w-2xl bg-white border border-slate-100 rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
            >
              
              {/* Modal Header */}
              <div className="p-6 border-b border-slate-100 flex items-start justify-between bg-slate-50">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono tracking-wider text-blue-600 uppercase font-semibold">
                      {activeModalDisease.category}
                    </span>
                    <span className={`px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded-full border ${getSeverityStyle(activeModalDisease.severity)}`}>
                      {activeModalDisease.severity} Risk
                    </span>
                  </div>
                  <h3 className="text-xl font-sans font-bold text-slate-900 mt-1">
                    {activeModalDisease.name}
                  </h3>
                </div>
                <button
                  id="close-disease-modal"
                  onClick={() => setActiveModalDisease(null)}
                  className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Modal Body (Scrollable) */}
              <div className="flex-1 p-6 space-y-6 overflow-y-auto">
                {/* Section: Overview */}
                <div className="space-y-2">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-widest flex items-center gap-1.5">
                    <Info className="w-4 h-4 text-blue-500" />
                    <span>Clinical Overview</span>
                  </span>
                  <p className="text-sm text-slate-600 leading-relaxed font-normal bg-blue-50/20 border border-blue-50/50 p-4 rounded-xl">
                    {activeModalDisease.overview}
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Section: Symptoms */}
                  <div className="space-y-3">
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-widest flex items-center gap-1.5">
                      <ChevronRight className="w-4 h-4 text-rose-500" />
                      <span>Symptom Profile</span>
                    </span>
                    <div className="space-y-2.5">
                      {activeModalDisease.symptoms.map((symp, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs text-slate-600 leading-relaxed">
                          <span className="w-1.5 h-1.5 rounded-full bg-rose-400 mt-1.5 shrink-0"></span>
                          <span>{symp}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Section: Prevention */}
                  <div className="space-y-3">
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-widest flex items-center gap-1.5">
                      <Shield className="w-4 h-4 text-emerald-500" />
                      <span>Prevention Protocol</span>
                    </span>
                    <div className="space-y-2.5">
                      {activeModalDisease.prevention.map((prev, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs text-slate-600 leading-relaxed">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
                          <span>{prev}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Section: Causes */}
                <div className="space-y-3 border-t border-slate-100 pt-5">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-widest flex items-center gap-1.5">
                    <HelpCircle className="w-4 h-4 text-violet-500" />
                    <span>Pathology & Causes</span>
                  </span>
                  <div className="space-y-2.5">
                    {activeModalDisease.causes.map((cause, i) => (
                      <div key={i} className="flex items-start gap-2.5 text-xs text-slate-600 leading-relaxed">
                        <span className="px-1.5 py-0.5 bg-violet-50 text-violet-600 text-[10px] font-bold rounded-md shrink-0">
                          {i + 1}
                        </span>
                        <span>{cause}</span>
                      </div>
                    ))}
                  </div>
                </div>

              </div>

              {/* Modal Footer */}
              <div className="p-4 bg-slate-50 border-t border-slate-100 text-center">
                <span className="text-[10px] text-slate-400 font-mono">
                  Educational Content Provided By HealthSphere AI. Not a clinical replacement.
                </span>
              </div>

            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
