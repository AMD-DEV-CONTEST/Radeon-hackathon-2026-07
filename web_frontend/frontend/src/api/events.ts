import type { FactoryFrontendEvent } from '@/types/protocol'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error' | 'reconnecting'

export interface EventStreamConfig {
  url: string
  onEvent: (event: FactoryFrontendEvent) => void
  onStatusChange: (status: ConnectionStatus) => void
  onError: (error: Error) => void
}

export class EventStreamClient {
  private source: EventSource | null = null
  private status: ConnectionStatus = 'disconnected'
  private seenEventIds = new Set<string>()

  constructor(private readonly config: EventStreamConfig) {}

  connect(): void {
    if (this.status === 'connected' || this.status === 'connecting') {
      return
    }
    this.updateStatus('connecting')
    this.source = new EventSource(this.config.url)
    this.source.addEventListener('open', this.handleOpen)
    this.source.addEventListener('factory_frontend_event', this.handleMessage)
    this.source.addEventListener('message', this.handleMessage)
    this.source.addEventListener('error', this.handleError)
  }

  disconnect(): void {
    if (this.source) {
      this.source.close()
      this.source.removeEventListener('open', this.handleOpen)
      this.source.removeEventListener('factory_frontend_event', this.handleMessage)
      this.source.removeEventListener('message', this.handleMessage)
      this.source.removeEventListener('error', this.handleError)
      this.source = null
    }
    this.updateStatus('disconnected')
  }

  getStatus(): ConnectionStatus {
    return this.status
  }

  private handleOpen = () => {
    this.updateStatus('connected')
  }

  private handleMessage = (event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data)
      const factoryEvent = data.kind === 'factory_frontend_event' ? data.event : data
      if (!factoryEvent?.event_id) return
      if (this.seenEventIds.has(factoryEvent.event_id)) return
      this.seenEventIds.add(factoryEvent.event_id)
      if (this.seenEventIds.size > 10000) {
        const firstId = this.seenEventIds.values().next().value
        if (firstId !== undefined) this.seenEventIds.delete(firstId)
      }
      this.config.onEvent(factoryEvent as FactoryFrontendEvent)
    } catch (error) {
      this.config.onError(error as Error)
    }
  }

  private handleError = () => {
    this.updateStatus(this.status === 'connected' ? 'reconnecting' : 'error')
    this.config.onError(new Error('SSE connection error'))
  }

  private updateStatus(status: ConnectionStatus): void {
    if (this.status === status) return
    this.status = status
    this.config.onStatusChange(status)
  }
}
