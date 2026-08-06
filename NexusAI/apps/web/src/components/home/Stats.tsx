"use client";
import CountUp from "react-countup";

const stats = [
  ["4", "Interactive Worlds"],
  ["100%", "Local AI"],
  ["0", "Cloud APIs"],
  ["GPU", "Accelerated"],
];

export default function Stats() {
  return (
    <section>
      <div className="grid gap-8 md:grid-cols-4">
        {stats.map(([number, label]) => (
          <div
            key={label}
            className="rounded-2xl border border-white/10 bg-[#080808]/70 p-8 text-center backdrop-blur-xl"
          >
            <h2 className="text-5xl font-bold text-cyan-400">
              <h2 className="text-5xl font-bold text-cyan-400">
                {number === "GPU" ? (
                  "GPU"
                ) : (
                  <CountUp
                    end={number === "100%" ? 100 : number === "4" ? 4 : 0}
                    duration={2}
                  />
                )}

                {number === "100%" && "%"}
              </h2>
            </h2>

            <p className="mt-4 text-white/60">{label}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
