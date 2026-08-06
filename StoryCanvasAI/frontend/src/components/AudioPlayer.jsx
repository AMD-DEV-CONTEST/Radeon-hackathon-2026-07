import { Volume2 } from "lucide-react";

export default function AudioPlayer({ src }) {
  return (
    <div className="mt-6">

      <div className="flex items-center gap-2 mb-2 text-slate-300">
        <Volume2 size={18} />
        <span>Narration</span>
      </div>

      <audio
        controls
        preload="metadata"
        className="w-full"
      >
        <source
          src={src}
          type="audio/wav"
        />

        Your browser does not support audio playback.
      </audio>

    </div>
  );
}