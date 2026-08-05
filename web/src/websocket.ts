/**
 * 全局单例 WebSocket 管理器
 * 避免多个组件重复创建连接导致内存泄漏
 */

type Subscriber = (data: any) => void

class WebSocketManager {
  private ws: WebSocket | null = null
  private subscribers: Set<Subscriber> = new Set()
  private reconnectTimer: number | null = null
  private closed = false
  private msgCount = 0

  connect() {
    // 已连接或正在连接时直接复用, 避免创建重复连接 (重复连接会导致每条消息双份推送)
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    // 复位 closed 标记, 否则 disconnect 过一次后将永远无法自动重连
    this.closed = false
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.ws = new WebSocket(`${wsProtocol}//${location.host}/ws`)

    this.ws.onopen = () => {
      console.log('[WebSocket] Connected')
      this.notifySubscribers({ type: 'connection', status: 'connected' })
    }

    this.ws.onclose = () => {
      console.log(`[WebSocket] Closed, received ${this.msgCount} messages total`)
      this.notifySubscribers({ type: 'connection', status: 'disconnected' })
      
      if (!this.closed) {
        this.reconnectTimer = window.setTimeout(() => this.connect(), 3000)
      }
    }

    this.ws.onerror = (err) => {
      console.error('[WebSocket] Error:', err)
    }

    this.ws.onmessage = (e) => {
      this.msgCount++
      try {
        const data = JSON.parse(e.data)
        this.notifySubscribers(data)
      } catch (err) {
        console.error('[WebSocket] Parse error:', err)
      }
    }
  }

  subscribe(callback: Subscriber): () => void {
    this.subscribers.add(callback)

    // 如果还没连接，立即连接; 已连接则立刻同步连接状态给新订阅者
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.connect()
    } else {
      callback({ type: 'connection', status: 'connected' })
    }

    // 返回取消订阅函数
    return () => {
      this.subscribers.delete(callback)
      
      // 如果没有订阅者了，关闭连接
      if (this.subscribers.size === 0) {
        this.disconnect()
      }
    }
  }

  private notifySubscribers(data: any) {
    this.subscribers.forEach(callback => {
      try {
        callback(data)
      } catch (err) {
        console.error('[WebSocket] Subscriber callback error:', err)
      }
    })
  }

  disconnect() {
    this.closed = true
    
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  getStatus(): 'connected' | 'disconnected' {
    return this.ws && this.ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected'
  }
}

// 全局单例
export const wsManager = new WebSocketManager()
