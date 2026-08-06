import { useState } from "react";

import Navbar from "../components/Navbar";
import PromptBox from "../components/PromptBox";
import GenerateButton from "../components/GenerateButton";
import LoadingScreen from "../components/LoadingScreen";
import StoryViewer from "../components/StoryViewer";
import DownloadPanel from "../components/DownloadPanel";
import Footer from "../components/Footer";

import {
  generateStory,
  getJobStatus,
  getStory,
} from "../services/api";

export default function Home() {

  const [prompt, setPrompt] = useState("");

  // NEW: Story length
  const [pages, setPages] = useState(5);

  const [storyData, setStoryData] = useState(null);

  const [loading, setLoading] = useState(false);

  const [progress, setProgress] = useState(0);

  const [status, setStatus] = useState("Waiting...");

  const [error, setError] = useState("");

  const handleGenerate = async () => {

    if (!prompt.trim()) {
      setError("Please enter a prompt.");
      return;
    }

    try {

      setLoading(true);

      setError("");

      setStoryData(null);

      setProgress(0);

      setStatus("Starting...");

      // Start generation
      const job = await generateStory(prompt, pages);

      const jobId = job.job_id;

      console.log("Job:", jobId);

      // Poll until completed
      const interval = setInterval(async () => {

        try {

          const state = await getJobStatus(jobId);

          setProgress(state.progress);

          setStatus(state.status);

          if (state.status === "Completed") {

            clearInterval(interval);

            const result = await getStory(jobId);

            setStoryData(result.story);

            setLoading(false);

          }

          if (state.status === "Failed") {

            clearInterval(interval);

            setLoading(false);

            setError(state.error);

          }

        } catch (err) {

          clearInterval(interval);

          setLoading(false);

          setError("Unable to fetch job status.");

        }

      }, 2000);

    } catch (err) {

      console.error(err);

      setLoading(false);

      setError(
        err.response?.data?.detail ||
        "Failed to start generation."
      );

    }

  };

  return (

    <div className="min-h-screen bg-slate-950 text-white">

      <Navbar />

      <main className="max-w-6xl mx-auto px-6 py-10">

        <PromptBox
          prompt={prompt}
          setPrompt={setPrompt}
        />

        {/* Story Length Dropdown */}
        <div className="mt-6">

          <label className="block text-lg font-semibold mb-2 text-slate-300">
            Story Length
          </label>

          <select
            value={pages}
            onChange={(e) => setPages(Number(e.target.value))}
            className="
              w-full
              rounded-xl
              bg-slate-900
              border
              border-slate-700
              px-4
              py-3
              text-white
              focus:outline-none
              focus:ring-2
              focus:ring-indigo-500
            "
          >
            <option value={3}>3 Pages</option>
            <option value={5}>5 Pages</option>
            <option value={7}>7 Pages</option>
            <option value={10}>10 Pages</option>
          </select>

        </div>

        <div className="mt-6">

          <GenerateButton
            loading={loading}
            onClick={handleGenerate}
          />

        </div>

        {error && (

          <p className="text-red-400 mt-6">

            {error}

          </p>

        )}

        {loading && (

          <LoadingScreen
            progress={progress}
            status={status}
          />

        )}

        {storyData && !loading && (

          <>

            <StoryViewer
              story={storyData}
            />

            <DownloadPanel />

          </>

        )}

      </main>

      <Footer />

    </div>

  );

}