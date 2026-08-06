import { Download } from "lucide-react";
import { API_BASE } from "../utils/constants";

export default function DownloadPanel() {
  return (
    <div
      className="
        mt-12
        p-6
        rounded-xl
        bg-slate-900
        border
        border-slate-700
      "
    >
      <h2 className="text-2xl font-bold mb-6">
        Downloads
      </h2>

      <div className="flex flex-wrap gap-4">

        <a
          href={`${API_BASE}/generated/pdf/story.pdf`}
          target="_blank"
          rel="noreferrer"
          className="
            flex
            items-center
            gap-2
            bg-blue-600
            hover:bg-blue-700
            px-5
            py-3
            rounded-lg
          "
        >
          <Download size={18} />
          Download PDF
        </a>

        <a
          href={`${API_BASE}/generated/videos/story.mp4`}
          target="_blank"
          rel="noreferrer"
          className="
            flex
            items-center
            gap-2
            bg-green-600
            hover:bg-green-700
            px-5
            py-3
            rounded-lg
          "
        >
          <Download size={18} />
          Download Video
        </a>

        <a
          href={`${API_BASE}/generated/stories/story.json`}
          target="_blank"
          rel="noreferrer"
          className="
            flex
            items-center
            gap-2
            bg-purple-600
            hover:bg-purple-700
            px-5
            py-3
            rounded-lg
          "
        >
          <Download size={18} />
          Download JSON
        </a>

      </div>
    </div>
  );
}