export default function ImageCard({ image }) {
  return (
    <div className="w-full overflow-hidden rounded-xl border border-slate-700">
      <img
        src={image}
        alt="Story Illustration"
        className="
          w-full
          object-cover
          rounded-xl
          hover:scale-105
          transition-transform
          duration-300
        "
      />
    </div>
  );
}