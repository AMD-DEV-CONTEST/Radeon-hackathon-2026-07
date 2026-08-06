import { WandSparkles } from "lucide-react";

export default function GenerateButton({
  loading,
  onClick,
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="
        flex
        items-center
        gap-2
        bg-blue-600
        hover:bg-blue-700
        px-6
        py-3
        rounded-xl
        font-semibold
        transition
        disabled:opacity-50
      "
    >
      <WandSparkles size={20} />

      {loading
        ? "Generating..."
        : "Generate Story"}
    </button>
  );
}