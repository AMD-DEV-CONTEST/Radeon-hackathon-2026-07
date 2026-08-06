import { useState } from 'react'
import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import { Play } from 'lucide-react'

interface TrainingModalProps {
  isOpen: boolean
  onClose: () => void
  datasets: Array<{ id: string; name: string; robotType: string }>
}

const MODEL_TYPES = [
  { id: 'act', name: 'ACT', description: 'Action Chunking with Transformers' },
  { id: 'diffusion', name: 'Diffusion Policy', description: 'Diffusion-based policy learning' },
]

export function TrainingModal({ isOpen, onClose, datasets }: TrainingModalProps) {
  const [modelName, setModelName] = useState('')
  const [selectedType, setSelectedType] = useState('act')
  const [selectedDataset, setSelectedDataset] = useState('')
  const [epochs, setEpochs] = useState(100)
  const [batchSize, setBatchSize] = useState(8)
  const [isTraining, setIsTraining] = useState(false)

  const handleStartTraining = () => {
    if (!modelName || !selectedDataset) return
    setIsTraining(true)

    // Simulate training start
    setTimeout(() => {
      setIsTraining(false)
      onClose()
      alert(`Training job "${modelName}" started! Check the Training page for progress.`)
    }, 1500)
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Train New Model">
      <div className="space-y-4">
        {/* Model Name */}
        <div>
          <label className="text-sm font-medium mb-2 block">Model Name</label>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="e.g., pick_place_v1"
            className="w-full p-2 rounded-lg border bg-[hsl(var(--background))] text-sm"
          />
        </div>

        {/* Model Type */}
        <div>
          <label className="text-sm font-medium mb-2 block">Model Type</label>
          <div className="space-y-2">
            {MODEL_TYPES.map(type => (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                className={`w-full p-3 rounded-lg border text-left transition-all ${
                  selectedType === type.id
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                    : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary))]/50'
                }`}
              >
                <div className="font-medium text-sm">{type.name}</div>
                <div className="text-xs text-[hsl(var(--muted-foreground))]">
                  {type.description}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Dataset Selection */}
        <div>
          <label className="text-sm font-medium mb-2 block">Training Dataset</label>
          <select
            value={selectedDataset}
            onChange={(e) => setSelectedDataset(e.target.value)}
            className="w-full p-2 rounded-lg border bg-[hsl(var(--background))] text-sm"
          >
            <option value="">Select a dataset...</option>
            {datasets.map(ds => (
              <option key={ds.id} value={ds.id}>
                {ds.name} ({ds.robotType})
              </option>
            ))}
          </select>
        </div>

        {/* Training Config */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Epochs: {epochs}</label>
            <input
              type="range"
              min="10"
              max="500"
              step="10"
              value={epochs}
              onChange={(e) => setEpochs(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">Batch Size: {batchSize}</label>
            <input
              type="range"
              min="1"
              max="32"
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            className="flex-1"
            onClick={onClose}
            disabled={isTraining}
          >
            Cancel
          </Button>
          <Button
            className="flex-1 gap-2"
            onClick={handleStartTraining}
            disabled={!modelName || !selectedDataset || isTraining}
          >
            {isTraining ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="h-4 w-4" />
                Start Training
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
