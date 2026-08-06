import { useState } from 'react'
import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import { Bot, Video, Move, RotateCcw } from 'lucide-react'
import type { Robot } from '../../types'

interface RobotControlModalProps {
  robot: Robot | null
  isOpen: boolean
  onClose: () => void
}

export function RobotControlModal({ robot, isOpen, onClose }: RobotControlModalProps) {
  const [isRecording, setIsRecording] = useState(false)
  const [frames, setFrames] = useState(0)

  if (!robot) return null

  const handleStartRecording = () => {
    setIsRecording(true)
    // Simulate frame counter
    const interval = setInterval(() => {
      setFrames(f => f + 1)
    }, 100)

    setTimeout(() => {
      clearInterval(interval)
      setIsRecording(false)
      setFrames(0)
    }, 5000)
  }

  const handleStopRecording = () => {
    setIsRecording(false)
    setFrames(0)
  }

  const handleHome = () => {
    alert(`Sending ${robot.name} to home position...`)
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Control: ${robot.name}`} className="max-w-lg">
      <div className="space-y-6">
        {/* Status */}
        <div className="flex items-center gap-4 p-4 rounded-lg bg-[hsl(var(--muted))]">
          <div className="h-12 w-12 rounded-xl bg-[hsl(var(--primary))]/10 flex items-center justify-center">
            <Bot className="h-6 w-6 text-[hsl(var(--primary))]" />
          </div>
          <div>
            <div className="font-medium">{robot.name}</div>
            <div className="text-sm text-[hsl(var(--muted-foreground))]">
              {robot.type} • {robot.status}
            </div>
          </div>
        </div>

        {/* Camera Preview */}
        <div>
          <label className="text-sm font-medium mb-2 block">Camera Feed</label>
          <div className="relative aspect-video rounded-lg bg-[hsl(var(--muted))] overflow-hidden flex items-center justify-center">
            {robot.cameraConnected ? (
              <>
                <div className="text-[hsl(var(--muted-foreground))]">Live camera feed would appear here</div>
                {isRecording && (
                  <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-red-500 rounded-full px-2 py-1">
                    <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
                    <span className="text-xs text-white font-medium">REC {frames}</span>
                  </div>
                )}
              </>
            ) : (
              <div className="text-[hsl(var(--muted-foreground))]">Camera offline</div>
            )}
          </div>
        </div>

        {/* Joint Controls */}
        {robot.jointPositions && (
          <div>
            <label className="text-sm font-medium mb-2 block">Joint Positions</label>
            <div className="grid grid-cols-3 gap-2">
              {robot.jointPositions.map((pos, i) => (
                <div key={i} className="p-2 rounded-lg bg-[hsl(var(--muted))] text-center">
                  <div className="text-xs text-[hsl(var(--muted-foreground))]">Joint {i + 1}</div>
                  <div className="font-mono text-sm">{pos.toFixed(2)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Control Buttons */}
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={handleHome}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Go Home
          </Button>
          <Button variant="outline">
            <Move className="h-4 w-4 mr-2" />
            Teleop
          </Button>
        </div>

        {/* Recording */}
        <div className="p-4 rounded-lg border border-[hsl(var(--border))]">
          <div className="flex items-center justify-between mb-3">
            <div className="font-medium">Data Recording</div>
            {isRecording && (
              <span className="text-xs text-red-400 flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                Recording
              </span>
            )}
          </div>
          <div className="flex gap-2">
            {isRecording ? (
              <Button variant="destructive" className="flex-1" onClick={handleStopRecording}>
                <Video className="h-4 w-4 mr-2" />
                Stop Recording
              </Button>
            ) : (
              <Button className="flex-1" onClick={handleStartRecording} disabled={!robot.cameraConnected}>
                <Video className="h-4 w-4 mr-2" />
                Start Recording
              </Button>
            )}
          </div>
        </div>

        {/* Close */}
        <Button variant="outline" className="w-full" onClick={onClose}>
          Close
        </Button>
      </div>
    </Modal>
  )
}
