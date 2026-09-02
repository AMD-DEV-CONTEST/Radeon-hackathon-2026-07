import React from "react";
import { IceCream, Menu, Search, Star, MapPin, ChevronRight } from "lucide-react";

export function AndroidBaselineMock({ color }: { color: string }) {
  return (
    <div className="flex items-center justify-center h-full w-full">
      {/* Device Frame */}
      <div
        className="relative bg-[#050a10] rounded-[36px] border-[4px] border-[#1f2937] shadow-2xl overflow-hidden"
        style={{ width: 280, height: 580 }}
      >
        {/* Status Bar */}
        <div className="h-6 flex items-center justify-between px-6 bg-black/40 text-label text-gray-400 font-bold">
          <span>10:24</span>
          <div className="flex gap-1.5 items-center">
            <div className="w-3 h-3 rounded-full bg-gray-500/50" />
            <div className="w-3 h-3 rounded-full bg-gray-500/50" />
            <div className="w-4 h-2.5 rounded-sm bg-gray-300" />
          </div>
        </div>

        {/* Top App Bar */}
        <div
          className="flex items-center justify-between px-5 pt-4 pb-3"
          style={{ borderBottom: `1px solid ${color}20` }}
        >
          <button className="p-1 rounded-full hover:bg-white/5 text-gray-300">
            <Menu size={20} />
          </button>
          <div className="font-bold tracking-widest text-body uppercase" style={{ color: color }}>
            Scoops
          </div>
          <button className="p-1 rounded-full hover:bg-white/5 text-gray-300">
            <Search size={20} />
          </button>
        </div>

        {/* Content Area */}
        <div className="p-5 flex flex-col gap-6 overflow-hidden h-[calc(100%-120px)]">
          {/* Header */}
          <div className="flex flex-col gap-1">
            <h2 className="text-xl font-black text-white">Find your flavor</h2>
            <p className="text-label text-gray-500 flex items-center gap-1">
              <MapPin size={12} className="text-gray-400" /> 123 Sweet Street
            </p>
          </div>

          {/* Featured Card */}
          <div
            className="w-full rounded-2xl p-4 flex items-center justify-between shadow-lg relative overflow-hidden"
            style={{
              background: `linear-gradient(135deg, ${color}20, transparent)`,
              border: `1px solid ${color}30`,
            }}
          >
            <div className="absolute -right-4 -bottom-4 opacity-10">
              <IceCream size={100} style={{ color: color }} />
            </div>
            <div className="flex flex-col gap-2 relative z-10">
              <span
                className="text-meta uppercase font-bold tracking-wider"
                style={{ color: color }}
              >
                Flavor of the week
              </span>
              <h3 className="text-lg font-bold text-white">Midnight Mint</h3>
              <div className="flex items-center gap-1 text-label text-gray-400 mt-1">
                <Star size={12} className="text-yellow-500 fill-yellow-500" /> 4.9 (128)
              </div>
            </div>
          </div>

          {/* Categories */}
          <div className="flex flex-col gap-3">
            <h4 className="text-body font-bold text-gray-300 uppercase tracking-wider">
              Categories
            </h4>
            <div className="flex gap-3 overflow-hidden">
              {["Cones", "Sundaes", "Pints"].map((cat, i) => (
                <div
                  key={i}
                  className="px-4 py-2 rounded-full text-label font-bold whitespace-nowrap"
                  style={{
                    background: i === 0 ? `${color}30` : "#161b22",
                    color: i === 0 ? color : "#9ca3af",
                    border: `1px solid ${i === 0 ? color + "50" : "#30363d"}`,
                  }}
                >
                  {cat}
                </div>
              ))}
            </div>
          </div>

          {/* List Items */}
          <div className="flex flex-col gap-3 flex-1 overflow-hidden">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="flex items-center gap-3 p-3 rounded-xl bg-[#161b22] border border-[#30363d]"
              >
                <div
                  className="w-12 h-12 rounded-lg flex items-center justify-center"
                  style={{ background: `${color}15`, border: `1px solid ${color}30` }}
                >
                  <IceCream size={20} style={{ color: color }} />
                </div>
                <div className="flex-1 flex flex-col gap-1">
                  <div className="h-3 rounded-full bg-gray-600 w-3/4" />
                  <div className="h-2 rounded-full bg-gray-700 w-1/2" />
                </div>
                <ChevronRight size={16} className="text-gray-500" />
              </div>
            ))}
          </div>
        </div>

        {/* Bottom Navigation */}
        <div className="absolute bottom-0 inset-x-0 h-16 bg-[#0d1117] border-t border-gray-800/80 flex items-center justify-around px-2 z-20">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col items-center gap-1.5 p-2">
              <div
                className="w-5 h-5 rounded-md"
                style={{
                  background: i === 0 ? `${color}25` : "transparent",
                  border: `1px solid ${i === 0 ? color + "50" : "transparent"}`,
                }}
              />
              <div
                className="w-4 h-1 rounded-full"
                style={{ background: i === 0 ? color : "#374151" }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
