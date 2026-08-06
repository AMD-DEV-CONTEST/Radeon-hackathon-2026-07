import AudioPlayer from "./AudioPlayer";
import { API_BASE } from "../utils/constants";

export default function StoryViewer({ story }) {

  if (!story) return null;

  return (
    <div className="mt-12">

      <h1 className="text-5xl font-bold">
        {story.title}
      </h1>

      <p className="text-slate-400 mt-3">
        {story.genre}
      </p>

      <div className="space-y-10 mt-10">

        {story.pages.map((page) => (

          <div
            key={page.page}
            className="
              bg-slate-900
              rounded-2xl
              p-6
              border
              border-slate-800
            "
          >

            <h2 className="text-3xl font-bold mb-5">
              Page {page.page}
            </h2>

            <img
              src={`${API_BASE}${page.image_url}`}
              alt={`Page ${page.page}`}
              className="
                w-full
                rounded-xl
                border
                border-slate-700
                mb-6
              "
            />

            <p className="leading-8 text-lg">
              {page.story}
            </p>

            <div className="mt-6">

              <AudioPlayer
                src={`${API_BASE}${page.audio_url}`}
              />

            </div>

          </div>

        ))}

      </div>

    </div>
  );
}