export default function LoadingScreen({ progress = 0, status = "Starting..." }) {
  return (
    <div className="mt-12 flex justify-center">
      <div className="w-full max-w-2xl rounded-3xl border border-slate-800 bg-slate-900/70 backdrop-blur-xl p-8 shadow-2xl">

        {/* Animated Icon */}
        <div className="flex justify-center">
          <div className="relative">
            <div className="h-16 w-16 rounded-full border-4 border-cyan-500 border-t-transparent animate-spin"></div>

            <div className="absolute inset-0 flex items-center justify-center text-2xl">
              📖
            </div>
          </div>
        </div>

        {/* Title */}
        <h2 className="mt-6 text-center text-2xl font-bold">
          Crafting Your Story
        </h2>

        <p className="mt-2 text-center text-slate-400">
          Our AI is writing, illustrating, and narrating your adventure...
        </p>

        {/* Progress */}
        <div className="mt-8">

          <div className="flex justify-between text-sm mb-2 text-slate-300">
            <span>{status}</span>
            <span>{progress}%</span>
          </div>

          <div className="h-3 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-600 transition-all duration-700"
              style={{ width: `${progress}%` }}
            />
          </div>

        </div>

        {/* Story Steps */}
        <div className="mt-8 grid grid-cols-2 gap-4 text-sm">

          <Step
            emoji="📝"
            title="Writing Story"
            active={status === "Generating Story"}
          />

          <Step
            emoji="🎨"
            title="Creating Artwork"
            active={status === "Generating Images"}
          />

          <Step
            emoji="🎙️"
            title="Recording Narration"
            active={status === "Generating Audio"}
          />

          <Step
            emoji="🎬"
            title="Building Video"
            active={status === "Building Video"}
          />

        </div>

        {/* Quote */}
        <p className="mt-8 text-center italic text-slate-500">
          "Every great adventure begins with a single idea..."
        </p>

      </div>
    </div>
  );
}

function Step({ emoji, title, active }) {
  return (
    <div
      className={`rounded-xl border p-4 transition-all duration-300 ${
        active
          ? "border-cyan-500 bg-cyan-500/10 scale-105"
          : "border-slate-800 bg-slate-900"
      }`}
    >
      <div className="text-2xl">{emoji}</div>

      <div className="mt-2 font-semibold">
        {title}
      </div>

      <div className="mt-1 text-xs text-slate-400">
        {active ? "In Progress..." : "Waiting"}
      </div>
    </div>
  );
}