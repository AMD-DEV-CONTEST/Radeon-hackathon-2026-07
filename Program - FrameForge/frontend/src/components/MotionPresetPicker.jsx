import "./MotionPresetPicker.css";

// Each preset gets a tiny animated SVG that mimes the actual camera move --
// a dot/frame moving the way the camera would -- so picking "Orbit" vs
// "Jib Up" is a glance, not a guess from a text label. This is the one
// deliberate visual risk in the app: everything else is quiet and
// disciplined so this can carry the personality.

const ICONS = {
  static: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--static" />
    </svg>
  ),
  dolly_in: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="2" className="motion-icon__subject motion-icon__subject--dolly-in" />
    </svg>
  ),
  dolly_out: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="6" className="motion-icon__subject motion-icon__subject--dolly-out" />
    </svg>
  ),
  dolly_left: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--dolly-left" />
    </svg>
  ),
  dolly_right: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--dolly-right" />
    </svg>
  ),
  jib_up: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--jib-up" />
    </svg>
  ),
  jib_down: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--jib-down" />
    </svg>
  ),
  orbit: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="2.5" className="motion-icon__subject motion-icon__subject--orbit-center" />
      <circle cx="24" cy="14" r="2" className="motion-icon__subject motion-icon__subject--orbit" />
    </svg>
  ),
  handheld: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame" />
      <circle cx="24" cy="24" r="3" className="motion-icon__subject motion-icon__subject--handheld" />
    </svg>
  ),
  custom: (
    <svg viewBox="0 0 48 48" className="motion-icon">
      <rect x="10" y="10" width="28" height="28" rx="2" className="motion-icon__frame motion-icon__frame--dashed" />
      <text x="24" y="28" textAnchor="middle" className="motion-icon__custom-mark">?</text>
    </svg>
  ),
};

export default function MotionPresetPicker({ presets, selectedId, onSelect }) {
  return (
    <div className="preset-grid" role="radiogroup" aria-label="Camera motion preset">
      {presets.map((preset) => {
        const isSelected = preset.id === selectedId;
        return (
          <button
            key={preset.id}
            type="button"
            role="radio"
            aria-checked={isSelected}
            className={`preset-card ${isSelected ? "preset-card--selected" : ""}`}
            onClick={() => onSelect(preset.id)}
          >
            {ICONS[preset.id] || ICONS.custom}
            <span className="preset-card__label">{preset.label}</span>
          </button>
        );
      })}
    </div>
  );
}
