import React, { useState } from "react";
import { EMERGENCY_CONTACTS, HOSPITAL_DIRECTORY } from "../data";
import { Phone, Copy, Check, MapPin, Navigation, Info, ShieldAlert } from "lucide-react";

export default function EmergencyHospitals() {
  const [copiedNumber, setCopiedNumber] = useState<string | null>(null);

  const handleCopy = (num: string) => {
    navigator.clipboard.writeText(num);
    setCopiedNumber(num);
    setTimeout(() => setCopiedNumber(null), 2000);
  };

  return (
    <div id="emergency-directory-view" className="space-y-8">
      
      {/* Overview Intro */}
      <div className="bg-white p-6 border border-slate-100 rounded-2xl shadow-sm space-y-3">
        <div className="space-y-1">
          <h2 id="emergency-title-h2" className="text-2xl font-sans font-bold tracking-tight text-slate-900">
            Emergency Contacts & Clinical Directories
          </h2>
          <p className="text-sm text-slate-500">
            Instant dial helplines and local healthcare facilities mapping directories (Simulated data).
          </p>
        </div>

        <div className="p-4 bg-amber-50 border border-amber-100 text-amber-800 rounded-xl flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-xs leading-relaxed font-medium">
            CRITICAL INFO: In an absolute physical health crisis, always dial the universal service <span className="font-bold underline">112 / 911</span> or drive directly to the closest state-certified trauma emergency room. Do not delay emergency transport for online assessments.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Helplines List */}
        <div className="space-y-4">
          <div className="space-y-1">
            <h3 className="text-base font-sans font-bold text-slate-900 tracking-tight">
              Rapid Helpline Directory
            </h3>
            <p className="text-xs text-slate-400">
              Direct hotlines for triage, disease outbreaks, and ambulance dispatches.
            </p>
          </div>

          <div className="space-y-3">
            {EMERGENCY_CONTACTS.map((contact, i) => (
              <div
                id={`emergency-contact-card-${i}`}
                key={i}
                className="p-4 bg-white border border-slate-100 rounded-2xl shadow-sm flex items-start justify-between gap-4"
              >
                <div className="space-y-1.5 flex-1">
                  <h4 className="text-sm font-sans font-bold text-slate-800 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                    {contact.name}
                  </h4>
                  <p className="text-[11px] text-slate-500 leading-normal font-normal">
                    {contact.description}
                  </p>
                  
                  {/* Styled call number display */}
                  <span className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 bg-blue-50 px-2.5 py-1 rounded-lg">
                    <Phone className="w-3 h-3" />
                    {contact.number}
                  </span>
                </div>

                <button
                  id={`btn-copy-num-${i}`}
                  onClick={() => handleCopy(contact.number)}
                  className="p-1.5 rounded-lg border border-slate-100 hover:border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-slate-700 transition cursor-pointer"
                  title="Copy number to clipboard"
                >
                  {copiedNumber === contact.number ? (
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Right 2 Columns: Hospitals list */}
        <div className="lg:col-span-2 space-y-4">
          <div className="space-y-1">
            <h3 className="text-base font-sans font-bold text-slate-900 tracking-tight">
              Nearby Clinical & Trauma Facilities
            </h3>
            <p className="text-xs text-slate-400">
              Nearest emergency rooms, specialized respiratory clinics, and diabetes wellness centers.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {HOSPITAL_DIRECTORY.map((hospital, i) => (
              <div
                id={`hospital-card-${i}`}
                key={i}
                className="p-5 bg-white border border-slate-100 rounded-2xl shadow-sm hover:border-blue-100 hover:shadow-md transition-all duration-300 flex flex-col justify-between"
              >
                <div className="space-y-3">
                  <div className="flex items-start justify-between">
                    <h4 className="text-sm font-sans font-bold text-slate-900 leading-snug">
                      {hospital.name}
                    </h4>
                    <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-[10px] font-bold rounded-md flex items-center gap-1 border border-slate-200">
                      <Navigation className="w-2.5 h-2.5 text-blue-500" />
                      {hospital.distance}
                    </span>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-start gap-1.5 text-xs text-slate-500 leading-relaxed font-normal">
                      <MapPin className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                      <span>{hospital.address}</span>
                    </div>

                    <div className="flex items-start gap-1.5 text-[11px] text-slate-500 leading-relaxed">
                      <Info className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-semibold text-slate-700 block">Focus Speciality:</span>
                        <span>{hospital.specialty}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="pt-4 mt-4 border-t border-slate-50 flex items-center justify-between text-xs font-semibold">
                  <span className="text-slate-400">Directory Line:</span>
                  <a href={`tel:${hospital.phone}`} className="text-blue-600 hover:underline">
                    {hospital.phone}
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>

    </div>
  );
}
