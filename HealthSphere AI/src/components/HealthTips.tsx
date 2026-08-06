import React from "react";
import { HEALTH_TIPS } from "../data";
import { Syringe, Droplets, Apple, Brain, Dumbbell, BriefcaseMedical } from "lucide-react";

export default function HealthTips() {
  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "Vaccination":
        return <Syringe className="w-5 h-5 text-blue-600" />;
      case "Hygiene":
        return <Droplets className="w-5 h-5 text-sky-500" />;
      case "Nutrition":
        return <Apple className="w-5 h-5 text-emerald-500" />;
      case "Mental Health":
        return <Brain className="w-5 h-5 text-indigo-500" />;
      case "Exercise":
        return <Dumbbell className="w-5 h-5 text-amber-500" />;
      default:
        return <BriefcaseMedical className="w-5 h-5 text-rose-500" />;
    }
  };

  return (
    <div id="health-tips-component" className="space-y-6">
      
      <div className="space-y-1">
        <h3 id="health-tips-title" className="text-lg font-sans font-bold text-slate-900 tracking-tight">
          Health Tips of the Day
        </h3>
        <p className="text-xs text-slate-500 font-medium">
          Evidence-based preventive recommendations for healthy communities.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {HEALTH_TIPS.map((tip, i) => (
          <div
            id={`health-tip-card-${i}`}
            key={i}
            className="p-5 bg-white border border-slate-100 rounded-2xl shadow-sm hover:shadow-md hover:border-blue-50 transition-all duration-300 flex items-start gap-4"
          >
            {/* Left side: Category Icon wrapped in safe frame */}
            <div className="p-2.5 bg-slate-50 border border-slate-100 rounded-xl shrink-0">
              {getCategoryIcon(tip.category)}
            </div>

            {/* Right side: Tip details */}
            <div className="space-y-1">
              <span className="text-[10px] font-mono font-bold tracking-wider text-slate-400 uppercase">
                {tip.category}
              </span>
              <h4 className="text-sm font-sans font-bold text-slate-900 leading-tight">
                {tip.title}
              </h4>
              <p className="text-xs text-slate-500 leading-relaxed font-normal">
                {tip.description}
              </p>
            </div>
          </div>
        ))}
      </div>

    </div>
  );
}
