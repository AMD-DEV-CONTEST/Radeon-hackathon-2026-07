import { useState } from 'react'
import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import { Video, Square } from 'lucide-react'

interface RecordingModalProps {
  isOpen: boolean
  onClose: () => void
  robots: Array<{ id: string; name: string; status: string }>
  datasets: Array<{ id: string; name: string }>
}

export function RecordingModal({ isOpen, onClose, robots, datasets }: RecordingModalProps) {
  const [selectedRobot, setSelectedRobot] = useState('')
  const [selectedDataset, setSelectedDataset] = useState('')
  const [episodes, setEpisodes] = useState(10)
  const [isRecording, setIsRecording] = useState(false)
  const [recordedFrames, setRecordedFrames] = useState(0)

  const handleStartRecording = () => {
    if (!selectedRobot || !selectedDataset) return
    setIsRecording(true)
    // Simulate recording progress
    const interval = setInterval(() => {
      setRecordedFrames(prev => prev + 1)
    }, 100)

    // Stop after 5 seconds for demo
    setTimeout(() => {
      clearInterval(interval)
      setIsRecording(false)
      setRecordedFrames(0)
      onClose()
    }, 5000)
  }

  const onlineRobots = robots.filter(r => r.status === 'online')

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Record Data">
      <div className="space-y-4">
        {/* Robot Selection */}
        <div>
          <label className="text-sm font-medium mb-2 block">Select Robot</label>
          <div className="grid grid-cols-2 gap-2">
            {onlineRobots.map(robot => (
              <button
                key={robot.id}
                onClick={() => setSelectedRobot(robot.id)}
                className={`p-3 rounded-lg border text-left transition-all ${
                  selectedRobot === robot.id
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10'
                    : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary))]/50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-green-500" />
                  <span className="text-sm font-medium">{robot.name}</span>
                </div>
              </button>
            ))}
          </div>
          {onlineRobots.length === 0 && (
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              No robots online. Please connect a robot first.
            </p>
          )}
        </div>

        {/* Dataset Selection */}
        <div>
          <label className="text-sm font-medium mb-2 block">Save to Dataset</label>
          <select
            value={selectedDataset}
            onChange={(e) => setSelectedDataset(e.target.value)}
            className="w-full p-2 rounded-lg border bg-[hsl(var(--background))] text-sm"
          >
            <option value="">Select or create new...</option>
            {datasets.map(ds => (
              <option key={ds.id} value={ds.id}>{ds.name}</option>
            ))}
          </select>
        </div>

        {/* Episodes */}
        <div>
          <label className="text-sm font-medium mb-2 block">
            Episodes: {episodes}
          </label>
          <input
            type="range"
            min="1"
            max="50"
            value={episodes}
            onChange={(e) => setEpisodes(Number(e.target.value))}
            className="w-full"
          />
        </div>

        {/* Recording Status */}
        {isRecording && (
          <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30">
            <div className="flex items-center gap-2 text-red-400">
              <div className="w-3 h-3 rounded-full bg-red-500 animate-pulse" />
              <span className="font-medium">Recording...</span>
            </div>
            <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
              Frames: {recordedFrames}
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            className="flex-1"
            onClick={onClose}
            disabled={isRecording}
          >
            Cancel
          </Button>
          <Button
            className="flex-1 gap-2"
            onClick={handleStartRecording}
            disabled={!selectedRobot || !selectedDataset || isRecording}
          >
            {isRecording ? (
              <>
                <Square className="h-4 w-4" />
                Recording...
              </>
            ) : (
              <>
                <Video className="h-4 w-4" />
                Start Recording
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
