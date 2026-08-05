/**
 * 全局数据缓存管理器
 * 避免多个组件重复请求相同数据
 */

type CacheEntry<T> = {
  data: T
  timestamp: number
  promise?: Promise<T>
}

class DataCacheManager {
  private cache = new Map<string, CacheEntry<any>>()
  private subscribers = new Map<string, Set<(data: any) => void>>()

  /**
   * 获取数据（带缓存）
   * @param key 缓存键
   * @param fetcher 获取数据的函数
   * @param ttl 缓存时间（毫秒），默认5秒
   */
  async fetch<T>(key: string, fetcher: () => Promise<T>, ttl: number = 5000): Promise<T> {
    const now = Date.now()
    const cached = this.cache.get(key)

    // 如果缓存有效，直接返回
    if (cached && now - cached.timestamp < ttl) {
      return cached.data
    }

    // 如果正在请求中，等待现有请求
    if (cached?.promise) {
      return cached.promise
    }

    // 发起新请求
    const promise = fetcher()

    // 先存储 promise，避免重复请求
    this.cache.set(key, { data: null as any, timestamp: now, promise })

    try {
      const data = await promise
      this.cache.set(key, { data, timestamp: now })
      this.notifySubscribers(key, data)
      return data
    } catch (err) {
      this.cache.delete(key)
      throw err
    }
  }

  /**
   * 订阅数据变化
   */
  subscribe<T>(key: string, callback: (data: T) => void): () => void {
    if (!this.subscribers.has(key)) {
      this.subscribers.set(key, new Set())
    }
    this.subscribers.get(key)!.add(callback)

    // 如果有缓存，立即通知
    const cached = this.cache.get(key)
    if (cached && cached.data) {
      callback(cached.data)
    }

    // 返回取消订阅函数
    return () => {
      const subs = this.subscribers.get(key)
      if (subs) {
        subs.delete(callback)
        if (subs.size === 0) {
          this.subscribers.delete(key)
        }
      }
    }
  }

  /**
   * 手动更新缓存（用于 WebSocket 推送）
   */
  update(key: string, data: any) {
    this.cache.set(key, { data, timestamp: Date.now() })
    this.notifySubscribers(key, data)
  }

  /**
   * 清除缓存
   */
  invalidate(key: string) {
    this.cache.delete(key)
  }

  private notifySubscribers(key: string, data: any) {
    const subs = this.subscribers.get(key)
    if (subs) {
      subs.forEach(callback => callback(data))
    }
  }

  /**
   * 获取缓存统计
   */
  getStats() {
    return {
      cacheSize: this.cache.size,
      subscriberKeys: this.subscribers.size,
    }
  }
}

export const dataCache = new DataCacheManager()
