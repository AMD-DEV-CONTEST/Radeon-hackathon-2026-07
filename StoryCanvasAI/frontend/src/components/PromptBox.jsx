export default function PromptBox({ prompt, setPrompt }) {
  return (
    <div className="w-full">
      <label className="block text-lg font-semibold mb-3">
        Describe your story
      </label>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={6}
        placeholder="Example: A little dragon becomes best friends with a lonely princess..."
        className="
          w-full
          rounded-xl
          bg-slate-900
          border
          border-slate-700
          p-4
          text-white
          resize-none
          outline-none
          focus:border-blue-500
        "
      />
    </div>
  );
}