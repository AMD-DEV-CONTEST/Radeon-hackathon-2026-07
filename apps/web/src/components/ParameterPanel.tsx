import { useAppStore } from '../store/appStore'

export function ParameterPanel() {
  const { plan, currentJob, brightness, shadowDensity, setBrightness, setShadowDensity } = useAppStore()

  const params = plan?.postprocess_params || currentJob?.print_report || {}

  return (
    <div className="space-y-4 rounded-2xl border border-neutral-300 bg-white/60 p-4">
      <div>
        <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-neutral-500">Rotation</label>
        <div className="flex gap-2">
          <button className="flex-1 rounded-lg border border-neutral-300 bg-neutral-800 py-2 text-xs text-white">Auto</button>
          <button className="flex-1 rounded-lg border border-neutral-300 bg-white py-2 text-xs text-neutral-600">Manual</button>
        </div>
      </div>

      <div>
        <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-neutral-500">Lighting</label>
        <div className="grid grid-cols-2 gap-2">
          <button className="rounded-lg border border-neutral-800 bg-neutral-800 py-2 text-xs text-white">Spot</button>
          <button className="rounded-lg border border-neutral-300 bg-white py-2 text-xs text-neutral-600">Area</button>
          <button className="rounded-lg border border-neutral-300 bg-white py-2 text-xs text-neutral-600">Target</button>
          <button className="rounded-lg border border-neutral-300 bg-white py-2 text-xs text-neutral-600">Sun</button>
        </div>
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Brightness</label>
          <span className="text-xs text-neutral-600">{brightness}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={brightness}
          onChange={(e) => setBrightness(Number(e.target.value))}
          className="w-full accent-neutral-800"
        />
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Shadow Density</label>
          <span className="text-xs text-neutral-600">{shadowDensity}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={shadowDensity}
          onChange={(e) => setShadowDensity(Number(e.target.value))}
          className="w-full accent-neutral-800"
        />
      </div>

      {Object.keys(params).length > 0 && (
        <div className="border-t border-neutral-300 pt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Print Params</p>
          <div className="space-y-1 text-xs text-neutral-600">
            {typeof params.target_height_mm === 'number' && <p>Target height: {params.target_height_mm} mm</p>}
            {typeof params.wall_thickness_mm === 'number' && <p>Wall thickness: {params.wall_thickness_mm} mm</p>}
            {typeof params.base_thickness_mm === 'number' && <p>Base thickness: {params.base_thickness_mm} mm</p>}
            {typeof params.relief_height_mm === 'number' && <p>Relief height: {params.relief_height_mm} mm</p>}
          </div>
        </div>
      )}
    </div>
  )
}
