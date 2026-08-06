import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../ui/card'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Bot, Wifi, WifiOff, Play, Square, Settings } from 'lucide-react'
// import { cn } from '../../lib/utils'
import type { Robot } from '../../types'

interface RobotCardProps {
  robot: Robot
  onConnect?: (id: string) => void
  onDisconnect?: (id: string) => void
  onControl?: (id: string) => void
}

export function RobotCard({ robot, onConnect, onDisconnect, onControl }: RobotCardProps) {
  const [imageError, setImageError] = useState(false)

  const statusConfig = {
    online: { variant: 'success' as const, icon: Wifi, text: 'Online' },
    offline: { variant: 'error' as const, icon: WifiOff, text: 'Offline' },
    busy: { variant: 'warning' as const, icon: Play, text: 'Busy' },
  }

  const config = statusConfig[robot.status]
  const StatusIcon = config.icon

  return (
    <Card className="overflow-hidden hover:border-primary/30 transition-all">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div>
              <CardTitle className="text-base">{robot.name}</CardTitle>
              <CardDescription className="text-xs">{robot.type}</CardDescription>
            </div>
          </div>
          <Badge variant={config.variant} className="gap-1">
            <StatusIcon className="h-3 w-3" />
            {config.text}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Camera Preview */}
        <div className="relative aspect-video rounded-lg bg-muted overflow-hidden">
          {robot.cameraConnected && robot.status === 'online' ? (
            <img
              src={`/api/v1/robots/${robot.id}/stream`}
              alt="Camera feed"
              className="w-full h-full object-cover"
              onError={() => setImageError(true)}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <WifiOff className="h-8 w-8 mb-2 opacity-50" />
              <span className="text-xs">Camera offline</span>
            </div>
          )}

          {/* Live indicator */}
          {robot.cameraConnected && robot.status === 'online' && !imageError && (
            <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-black/60 rounded-full px-2 py-1">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-xs text-white font-medium">LIVE</span>
            </div>
          )}
        </div>

        {/* Joint Positions */}
        {robot.jointPositions && robot.jointPositions.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">Joint Positions</div>
            <div className="flex flex-wrap gap-1">
              {robot.jointPositions.slice(0, 6).map((pos, i) => (
                <code key={i} className="text-xs bg-muted px-1.5 py-0.5 rounded">
                  {pos.toFixed(2)}
                </code>
              ))}
              {robot.jointPositions.length > 6 && (
                <span className="text-xs text-muted-foreground">+{robot.jointPositions.length - 6}</span>
              )}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          {robot.status === 'offline' ? (
            <Button
              size="sm"
              className="flex-1"
              onClick={() => onConnect?.(robot.id)}
            >
              <Wifi className="h-4 w-4 mr-1" />
              Connect
            </Button>
          ) : (
            <>
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => onControl?.(robot.id)}
              >
                <Settings className="h-4 w-4 mr-1" />
                Control
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onDisconnect?.(robot.id)}
              >
                <Square className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
