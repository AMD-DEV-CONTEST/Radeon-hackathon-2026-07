/**
 * Feetech WebSerial 驱动 — 浏览器直连串口总线（零安装）
 *
 * 对应设计：docs/webserial-design.md（S1 · 协议层移植）
 * 移植自：apps/realtime/dora-bambot/_next/static/chunks/881-47c588f365fe1541.js
 *   （bambot.org 快照内的完整浏览器 Feetech 实现），本文件为其类型化 + 中文注释版。
 *
 * 协议：Feetech STS/SMS 串口总线（Dynamixel 风格），默认波特率 1_000_000，
 *   包形 [FF FF ID LEN INST PARAMS… CHK]，CHK = ~(Σ ID..PARAMS) & 0xFF。
 *   指令：0x01 PING / 0x02 READ / 0x03 WRITE / 0x82 SYNC READ / 0x83 SYNC WRITE。
 * 边界：仅 Feetech 总线（SO-101 主线）；Reachy（Dynamixel）与 B601（Robstride CAN）不属本路径。
 *
 * 安全纪律（沿用仓库 AGENTS.md）：只读/安全命令（ping、read、write goal position）；
 * 不写寄存器参数、不改电机 ID、不设零点；写命令拒绝广播 ID 254。
 */

// ---------------------------------------------------------------------------
// 环境声明：TS lib.dom 尚未收录 Web Serial API（TS 5.9），此处按 W3C 规范补最小面
// ---------------------------------------------------------------------------
declare global {
  interface SerialPortInfo {
    usbVendorId?: number
    usbProductId?: number
  }
  interface SerialPort {
    readonly readable: ReadableStream<Uint8Array>
    readonly writable: WritableStream<Uint8Array>
    open(options: {
      baudRate: number
      dataBits?: number
      stopBits?: number
      parity?: 'none' | 'even' | 'odd'
      bufferSize?: number
      flowControl?: 'none' | 'hardware'
    }): Promise<void>
    close(): Promise<void>
    getInfo(): SerialPortInfo
  }
  interface Serial {
    requestPort(options?: {
      filters?: Array<{ usbVendorId?: number; usbProductId?: number }>
    }): Promise<SerialPort>
    getPorts(): Promise<SerialPort[]>
  }
  interface Navigator {
    serial?: Serial
  }
}

// ---------------------------------------------------------------------------
// 类型与常量
// ---------------------------------------------------------------------------

/** 事务错误码（与参考实现一致，0 = 成功） */
export type TxRxErrorCode = 0 | -1 | -2 | -3 | -4 | -5 | -6 | -7 | -9

export interface TxRxResult {
  /** 收到的完整状态包（raw bytes），失败时为空数组 */
  packet: number[]
  /** 事务错误码，0 = 成功 */
  error: TxRxErrorCode
  /** 设备错误寄存器值（bit 标志，见 rxPacketErrorText） */
  errno: number
}

export interface PingResult {
  /** 电机型号（读自地址 3，2 字节），读失败为 0 */
  model: number
  error: TxRxErrorCode
  errno: number
}

/** 常用寄存器地址（STS3215，与 LeRobot 对齐）；更多地址按需补充 */
export const Registers = {
  TORQUE_ENABLE: 0x28, // 40
  GOAL_POSITION: 0x2a, // 42
  PRESENT_POSITION: 0x38, // 56
} as const

/** 字节序辅助（STS/SMS 小端：低字节在前） */
const loByte = (n: number) => n & 0xff
const hiByte = (n: number) => (n >> 8) & 0xff
const hiWord = (n: number) => (n >> 16) & 0xffff
const wordFrom = (lo: number, hi: number) => ((hi << 8) | lo) & 0xffff
const dwordFrom = (low: number, high: number) => (((high << 16) | low) >>> 0)

/** 事务错误码文案 */
export function txRxResultText(code: TxRxErrorCode): string {
  switch (code) {
    case 0: return '[TxRxResult] Communication success!'
    case -1: return '[TxRxResult] Port is in use!'
    case -2: return '[TxRxResult] Failed transmit instruction packet!'
    case -3: return '[TxRxResult] Failed get status packet from device!'
    case -4: return '[TxRxResult] Incorrect instruction packet!'
    case -5: return '[TxRxResult] Now receiving status packet!'
    case -6: return '[TxRxResult] There is no status packet!'
    case -7: return '[TxRxResult] Incorrect status packet!'
    case -9: return '[TxRxResult] Protocol does not support this function!'
    default: return `[TxRxResult] Unknown code ${code}`
  }
}

/** 状态包 error 字节的 bit 标志文案 */
export function rxPacketErrorText(flag: number): string {
  if (flag & 0x01) return '[RxPacketError] Input voltage error!'
  if (flag & 0x02) return '[RxPacketError] Angle sen error!'
  if (flag & 0x04) return '[RxPacketError] Overheat error!'
  if (flag & 0x08) return '[RxPacketError] OverEle error!'
  if (flag & 0x20) return '[RxPacketError] Overload error!'
  return ''
}

// ---------------------------------------------------------------------------
// 串口层
// ---------------------------------------------------------------------------

export class FeetechSerialPort {
  port: SerialPort | null = null
  reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  writer: WritableStreamDefaultWriter<Uint8Array> | null = null
  isOpen = false
  /** 单事务占用标记：一个 txRx 未完成前不允许新事务 */
  isUsing = false
  baudRate: number
  private packetStartTime = 0
  private packetTimeout = 0
  private txTimePerByte = 0
  /**
   * 超读字节缓冲：Web Streams 按 chunk 整块交付（不能 slice 丢弃尾巴），
   * 超读部分留在缓冲供下一次 read 消费；事务边界由 clear() 清掉。
   */
  private rxBuf: number[] = []
  /**
   * 进行中的 read() promise（Web Streams 同一 reader 只允许一个 pending read；
   * 超时不能丢弃它，否则下一次 read() 抛 TypeError 且 reader 永久卡死——
   * 真机无响应（首次上电最常见）时必现。见 M42 审查修复）。
   */
  private pendingRead: Promise<ReadResult> | null = null

  constructor(baudRate = 1_000_000) {
    this.baudRate = baudRate
    this.txTimePerByte = (1000 / baudRate) * 10
  }

  /** 弹出浏览器设备选择框（必须由用户手势触发），用户取消返回 false */
  async requestPort(): Promise<boolean> {
    try {
      this.port = await navigator.serial!.requestPort()
      return true
    } catch {
      return false
    }
  }

  /** 绑定一个已授权/已枚举的原生端口（诊断用：同一端口多波特率探测，避免重复弹授权框） */
  attachGrantedPort(port: SerialPort): void {
    this.port = port
  }

  async open(): Promise<boolean> {
    if (!this.port) return false
    try {
      await this.port.open({ baudRate: this.baudRate })
      this.reader = this.port.readable.getReader()
      this.writer = this.port.writable.getWriter()
      this.isOpen = true
      this.txTimePerByte = (1000 / this.baudRate) * 10
      return true
    } catch {
      return false
    }
  }

  async close(): Promise<void> {
    if (this.reader) {
      try {
        await this.reader.releaseLock()
      } catch {
        // pending read 未 settle（设备无响应）时 releaseLock 抛错——放弃该 reader，
        // 由后续 port.close() 兜底
      }
      this.reader = null
      this.pendingRead = null
    }
    if (this.writer) {
      await this.writer.releaseLock()
      this.writer = null
    }
    if (this.port && this.isOpen) {
      await this.port.close()
      this.isOpen = false
    }
  }

  /**
   * 丢弃读缓冲：释放旧 reader 并重新挂接（事务前调用，防止残留字节干扰帧同步）。
   * 若存在未 settle 的 pending read 则跳过（releaseLock 会抛错；该 read 一旦
   * resolve 数据即被吞掉，等价于清缓冲）。
   */
  async clear(): Promise<void> {
    if (this.reader) {
      if (this.pendingRead) {
        this.rxBuf = [] // 超时残留：清缓冲，pending read 的数据由下一次 read 消费
        return
      }
      this.rxBuf = []
      await this.reader.releaseLock()
      this.reader = this.port!.readable.getReader()
    }
  }

  setBaudRate(baudRate: number): void {
    this.baudRate = baudRate
    this.txTimePerByte = (1000 / baudRate) * 10
  }

  /** 写入一包（内部负责加校验和见 FeetechProtocol.txPacket），返回写入字节数，失败 0 */
  async write(packet: number[]): Promise<number> {
    if (!this.isOpen || !this.writer) return 0
    try {
      await this.writer.write(new Uint8Array(packet))
      return packet.length
    } catch {
      return 0
    }
  }

  /**
   * 读到至多 maxBytes 字节；分块超时 100ms，总超时 500ms，超时返回已收到的内容。
   * 超时不会丢弃 pending read：复用同一 promise（M42 死锁修复），数据到达后
   * 由下一个 read() 消费；超长 chunk 裁剪到 maxBytes。
   */
  async read(maxBytes: number): Promise<number[]> {
    if (!this.isOpen || !this.reader) return []
    try {
      const out: number[] = []
      const start = performance.now()
      while (out.length < maxBytes) {
        if (performance.now() - start > 500) break
        // 先用超读缓冲（上一 chunk 的尾巴）
        if (this.rxBuf.length > 0) {
          out.push(...this.rxBuf.splice(0, maxBytes - out.length))
          continue
        }
        if (!this.pendingRead) this.pendingRead = this.reader.read() as Promise<ReadResult>
        const timedOut: ReadResult = { value: new Uint8Array(0), done: false, timeout: true }
        const chunk = await Promise.race<ReadResult>([
          this.pendingRead,
          new Promise<ReadResult>((resolve) => setTimeout(() => resolve(timedOut), 100)),
        ])
        if (chunk.timeout) continue // 继续等同一个 pendingRead，不发起新 read
        this.pendingRead = null
        if (chunk.done) break // 流关闭
        if (chunk.value.length === 0) {
          await new Promise((resolve) => setTimeout(resolve, 10))
          continue
        }
        out.push(...Array.from(chunk.value))
        // 超读部分留给下一次 read（不能丢弃：帧同步要靠完整的包）
        const excess = out.length - maxBytes
        if (excess > 0) {
          this.rxBuf = out.splice(maxBytes, excess)
        }
        if (out.length >= maxBytes) break
      }
      return out
    } catch {
      return []
    }
  }

  setPacketTimeout(bytes: number): void {
    this.packetStartTime = this.getCurrentTime()
    this.packetTimeout = this.txTimePerByte * bytes + 34
  }

  setPacketTimeoutMillis(ms: number): void {
    this.packetStartTime = this.getCurrentTime()
    this.packetTimeout = ms
  }

  isPacketTimeout(): boolean {
    if (this.getTimeSinceStart() > this.packetTimeout) {
      this.packetTimeout = 0
      return true
    }
    return false
  }

  private getCurrentTime(): number {
    return performance.now()
  }

  private getTimeSinceStart(): number {
    let elapsed = this.getCurrentTime() - this.packetStartTime
    if (elapsed < 0) this.packetStartTime = this.getCurrentTime()
    return elapsed
  }
}

type ReadResult = { value: Uint8Array; done: boolean; timeout?: boolean }

// ---------------------------------------------------------------------------
// 协议层
// ---------------------------------------------------------------------------

export class FeetechProtocol {
  /** 0 = STS/SMS（小端），1 = SCS（大端） */
  readonly protocolEnd: 0 | 1

  constructor(protocolEnd: 0 | 1 = 0) {
    this.protocolEnd = protocolEnd
  }

  /** 写一包：加 FF FF 头与校验和并发送；错误码 -1 占用 / -2 写失败 / -4 包超长 */
  private async txPacket(port: FeetechSerialPort, packet: number[]): Promise<TxRxErrorCode> {
    let sum = 0
    // 包总长 = LEN + 4（FF FF + ID + LEN + 校验和都在 LEN 之外计数）
    const len = packet[3] + 4
    if (port.isUsing) return -1
    port.isUsing = true
    if (len > 250) {
      port.isUsing = false
      return -4
    }
    packet[0] = 0xff
    packet[1] = 0xff
    for (let i = 2; i < len - 1; i++) sum += packet[i]
    packet[len - 1] = loByte(~sum)
    await port.clear()
    if (len !== (await port.write(packet))) {
      port.isUsing = false
      return -2
    }
    return 0
  }

  /** 读一包：帧头同步（FF FF）、按 LEN 收全、校验和与 ID 校验 */
  private async rxPacket(port: FeetechSerialPort): Promise<[number[], TxRxErrorCode]> {
    const bytes: number[] = []
    let error: TxRxErrorCode = -3
    let expectLen = 6 // 最小状态包总长：FF FF ID LEN ERROR CHK
    for (;;) {
      const chunk = await port.read(expectLen - bytes.length)
      bytes.push(...chunk)
      if (bytes.length >= expectLen) {
        let headerAt = -1
        for (let i = 0; i < bytes.length - 1; i++) {
          if (bytes[i] === 0xff && bytes[i + 1] === 0xff) {
            headerAt = i
            break
          }
        }
        if (headerAt === 0) {
          if (bytes[2] > 253 || bytes[3] > 250) {
            bytes.shift()
            continue
          }
          const need = bytes[3] + 4
          if (need !== expectLen) {
            expectLen = need
            continue
          }
          if (bytes.length < need) {
            if (port.isPacketTimeout()) {
              error = bytes.length === 0 ? -6 : -7
              break
            }
            continue
          }
          let sum = 0
          for (let i = 2; i < need - 1; i++) sum += bytes[i]
          error = bytes[need - 1] === loByte(~sum) ? 0 : -7
          break
        }
        if (headerAt > 0) {
          bytes.splice(0, headerAt)
          continue
        }
      }
      if (port.isPacketTimeout()) {
        error = bytes.length === 0 ? -6 : -7
        break
      }
    }
    return [bytes, error]
  }

  /** 完整事务：TX → （非广播）RX → 校验响应 ID */
  private async txRxPacket(
    port: FeetechSerialPort,
    packet: number[],
  ): Promise<TxRxResult> {
    const empty: TxRxResult = { packet: [], error: -3, errno: 0 }
    try {
      if (port.isUsing) return { packet: [], error: -1, errno: 0 }
      const tx = await this.txPacket(port, packet)
      if (tx !== 0) {
        port.isUsing = false
        return { packet: [], error: tx, errno: 0 }
      }
      // 广播写（ID 254）无响应，事务即完成
      if (packet[2] === 254) {
        port.isUsing = false
        return { packet: [], error: 0, errno: 0 }
      }
      // READ 指令（0x02）按请求字节数+10 设超时，其余按 10 字节标准包
      if (packet[4] === 0x02) port.setPacketTimeout(packet[6] + 10)
      else port.setPacketTimeout(10)
      await port.clear()
      const [rx, err] = await this.rxPacket(port)
      if (err !== 0) {
        port.isUsing = false
        return { packet: rx, error: err, errno: 0 }
      }
      if (rx.length < 6) {
        port.isUsing = false
        return { packet: rx, error: -7, errno: 0 }
      }
      if (rx[2] !== packet[2]) {
        port.isUsing = false
        return { packet: rx, error: -7, errno: 0 }
      }
      const result: TxRxResult = { packet: rx, error: 0, errno: rx[4] }
      port.isUsing = false
      return result
    } catch {
      port.isUsing = false
      return empty
    }
  }

  /** ping 电机：PING 指令 + 读型号（地址 3，2 字节） */
  async ping(port: FeetechSerialPort, id: number): Promise<PingResult> {
    if (id >= 254) return { model: 0, error: -9, errno: 0 }
    const pkt = [0, 0, id, 2, 0x01] // [FF FF ID LEN(2) PING CHK] LEN=2 含指令+校验和
    const txr = await this.txRxPacket(port, pkt)
    if (txr.error !== 0) return { model: 0, error: txr.error, errno: txr.errno }
    const [model, error, errno] = await this.readTxRx(port, id, 3, 2)
    if (error !== 0) return { model: 0, error, errno }
    const b0 = model[0]
    const b1 = model[1]
    return { model: this.protocolEnd === 0 ? wordFrom(b0, b1) : wordFrom(b1, b0), error: 0, errno }
  }

  /** READ：读 count 字节（地址 addr 起），返回原始数据字节 */
  async readTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
    count: number,
  ): Promise<[number[], TxRxErrorCode, number]> {
    if (id >= 254) return [[], -9, 0]
    const pkt = [0, 0, id, 4, 0x02, addr, count]
    const txr = await this.txRxPacket(port, pkt)
    if (txr.error !== 0) return [[], txr.error, txr.errno]
    if (!txr.packet || txr.packet.length < 5 + count) return [[], -7, 0]
    const data: number[] = []
    for (let i = 0; i < count; i++) data.push(txr.packet[5 + i])
    return [data, 0, txr.errno]
  }

  async read1ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
  ): Promise<[number, TxRxErrorCode, number]> {
    const [data, error, errno] = await this.readTxRx(port, id, addr, 1)
    return [data.length > 0 ? data[0] : 0, error, errno]
  }

  async read2ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
  ): Promise<[number, TxRxErrorCode, number]> {
    const [data, error, errno] = await this.readTxRx(port, id, addr, 2)
    if (data.length < 2) return [0, error, errno]
    return [wordFrom(data[0], data[1]), error, errno]
  }

  async read4ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
  ): Promise<[number, TxRxErrorCode, number]> {
    const [data, error, errno] = await this.readTxRx(port, id, addr, 4)
    if (data.length < 4) return [0, error, errno]
    return [dwordFrom(wordFrom(data[0], data[1]), wordFrom(data[2], data[3])), error, errno]
  }

  /** WRITE：写 data 字节到地址 addr；返回 [errno, error] */
  async writeTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
    data: number[],
  ): Promise<[number, TxRxErrorCode]> {
    // 广播 ID 拒绝：契约是 [errno, error]，error=-9 让调用方看到失败（M42 审查 #3：
    // 此前返回 [-9, 0] 被「只查 error」的调用方误判为成功）
    if (id >= 254) return [0, -9]
    const n = data.length
    const pkt = [0, 0, id, n + 3, 0x03, addr]
    for (let i = 0; i < n; i++) pkt.push(loByte(data[i]))
    const txr = await this.txRxPacket(port, pkt)
    return [txr.errno, txr.error]
  }

  async write1ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
    value: number,
  ): Promise<[number, TxRxErrorCode]> {
    return this.writeTxRx(port, id, addr, [loByte(value)])
  }

  async write2ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
    value: number,
  ): Promise<[number, TxRxErrorCode]> {
    return this.writeTxRx(port, id, addr, [loByte(value), hiByte(value)])
  }

  async write4ByteTxRx(
    port: FeetechSerialPort,
    id: number,
    addr: number,
    value: number,
  ): Promise<[number, TxRxErrorCode]> {
    return this.writeTxRx(port, id, addr, [
      loByte(value & 0xffff),
      hiByte(value & 0xffff),
      loByte(hiWord(value)),
      hiByte(hiWord(value)),
    ])
  }

  /** SYNC READ（广播 0xFE，指令 0x82）：一次读多个电机同一地址；只发不收，返回错误码 */
  async syncReadTx(
    port: FeetechSerialPort,
    addr: number,
    count: number,
    ids: number[],
  ): Promise<TxRxErrorCode> {
    const i = ids.length
    const pkt = [0, 0, 254, i + 4, 0x82, addr, count]
    for (let k = 0; k < i; k++) pkt.push(ids[k])
    const total = pkt[3] + 4
    pkt[0] = 0xff
    pkt[1] = 0xff
    let sum = 0
    for (let k = 2; k < total - 1; k++) sum += pkt[k]
    pkt[total - 1] = loByte(~sum)
    await port.clear()
    if ((await port.write(pkt)) !== total) return -2
    port.setPacketTimeout((6 + count) * i)
    return 0
  }

  /**
   * SYNC WRITE（广播 0xFE，指令 0x83）：一次写多电机同一地址；只发不收，返回错误码。
   * LEN = data.length + 4（inst + addr + count + data + 校验和）。
   * 注意：原始 bambot 快照的形参 i 是「数据总长」而非电机数（本移植曾误读为电机数，
   * 由冒烟测试 8.6 逐字节比对发现并修正）。
   */
  async syncWriteTxOnly(
    port: FeetechSerialPort,
    addr: number,
    count: number,
    data: number[],
  ): Promise<TxRxErrorCode> {
    const pkt = [0, 0, 254, data.length + 4, 0x83, addr, count]
    for (const b of data) pkt.push(loByte(b))
    const total = pkt[3] + 4
    pkt[0] = 0xff
    pkt[1] = 0xff
    let sum = 0
    for (let k = 2; k < total - 1; k++) sum += pkt[k]
    pkt[total - 1] = loByte(~sum)
    await port.clear()
    if ((await port.write(pkt)) !== total) return -2
    return 0
  }
}

// ---------------------------------------------------------------------------
// 便捷入口（供 UI 调用）
// ---------------------------------------------------------------------------

export interface WebSerialConnection {
  port: FeetechSerialPort
  protocol: FeetechProtocol
}

/** 特性检测：Chrome/Edge 桌面（Safari/Firefox 不支持） */
export function isWebSerialSupported(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.serial !== 'undefined'
}

/**
 * 一键连接：选口 → 打开（默认波特率 1e6）→ 返回 { port, protocol }。
 * 用户取消选口或打开失败返回 null（调用方自行提示）。
 */
export async function connectWebSerial(
  options: { baudRate?: number; protocolEnd?: 0 | 1 } = {},
): Promise<WebSerialConnection | null> {
  if (!isWebSerialSupported()) return null
  const port = new FeetechSerialPort(options.baudRate ?? 1_000_000)
  if (!(await port.requestPort())) return null
  if (!(await port.open())) {
    await port.close()
    return null
  }
  return { port, protocol: new FeetechProtocol(options.protocolEnd ?? 0) }
}

/**
 * 高阶层 SO-101 总线（收敛自 lib/webserial/sts3215.ts 的 StsSerialBus，
 * 底层复用 FeetechSerialPort + FeetechProtocol）。
 * API 面：requestAndOpen / scan / ping / readPosition / writePosition / setTorque / close。
 */
export class StsSerialBus {
  private conn: WebSerialConnection | null = null
  private busy = false

  get connected(): boolean {
    return this.conn != null && this.conn.port.isOpen
  }

  /** 弹授权框并打开串口（默认 1e6 波特率）；用户取消/失败抛错 */
  async requestAndOpen(baudRate = 1_000_000): Promise<void> {
    if (!isWebSerialSupported()) {
      throw new Error('当前浏览器不支持 WebSerial。请使用 Chrome 或 Edge。')
    }
    const conn = await connectWebSerial({ baudRate })
    if (!conn) throw new Error('串口连接失败或已取消')
    this.conn = conn
  }

  async close(): Promise<void> {
    if (this.conn) await this.conn.port.close()
    this.conn = null
  }

  /** 单事务串行化：同一时刻只允许一个协议事务 */
  private async tx<T>(
    fn: (protocol: FeetechProtocol, port: FeetechSerialPort) => Promise<T>,
  ): Promise<T> {
    if (!this.conn) throw new Error('串口未连接')
    if (this.busy) throw new Error('串口忙')
    this.busy = true
    try {
      return await fn(this.conn.protocol, this.conn.port)
    } finally {
      this.busy = false
    }
  }

  async ping(id: number): Promise<boolean> {
    return this.tx(async (protocol, port) => (await protocol.ping(port, id)).error === 0)
  }

  /** 逐 ID ping，返回在线电机列表（间隔 8ms，避免总线抖动） */
  async scan(ids: number[] = [1, 2, 3, 4, 5, 6]): Promise<number[]> {
    const found: number[] = []
    for (const id of ids) {
      if (await this.ping(id)) found.push(id)
      await new Promise((r) => setTimeout(r, 8))
    }
    return found
  }

  async readPosition(id: number): Promise<number> {
    return this.tx(async (protocol, port) => {
      const [value, error] = await protocol.read2ByteTxRx(port, id, Registers.PRESENT_POSITION)
      if (error !== 0) throw new Error(`读位置失败 (id=${id})`)
      return value
    })
  }

  /** 写目标位置（钳制 0..4095，LE 字序） */
  async writePosition(id: number, position: number): Promise<void> {
    const value = Math.max(0, Math.min(4095, Math.round(position)))
    await this.tx(async (protocol, port) => {
      const [, error] = await protocol.write2ByteTxRx(port, id, Registers.GOAL_POSITION, value)
      if (error !== 0) throw new Error(`写位置失败 (id=${id})`)
    })
  }

  async setTorque(id: number, enabled: boolean): Promise<void> {
    await this.tx(async (protocol, port) => {
      const [, error] = await protocol.write1ByteTxRx(
        port,
        id,
        Registers.TORQUE_ENABLE,
        enabled ? 1 : 0,
      )
      if (error !== 0) throw new Error(`扭矩设置失败 (id=${id})`)
    })
  }

  /**
   * 同步广播写目标位置（一条 0x83 包写多电机，半双工友好，挥手/动作序列专用）。
   * 每电机 3 字节：[ID, lo, hi]（count=2）。
   * 注意：不用 4 字节布局——第 4 字节落在 GOAL_TIME(0x2C)，写 0 会把平滑动作
   * 变成全速冲击（M42 审查高危 #2）。
   */
  async writePositionsMany(entries: Array<{ id: number; value: number }>): Promise<void> {
    if (entries.length === 0) return
    const data: number[] = []
    for (const { id, value } of entries) {
      const v = Math.max(0, Math.min(4095, Math.round(value)))
      data.push(id, loByte(v), hiByte(v))
    }
    await this.tx(async (protocol, port) => {
      const err = await protocol.syncWriteTxOnly(port, Registers.GOAL_POSITION, 2, data)
      if (err !== 0) throw new Error(`同步写位置失败 (${err})`)
    })
  }

  /**
   * 急停：广播关扭矩（真机安全；只发不收）。每个电机 2 字节：[ID, 0]。
   */
  async emergencyStop(ids: number[] = [1, 2, 3, 4, 5, 6]): Promise<void> {
    const data: number[] = []
    for (const id of ids) data.push(id, 0)
    await this.tx(async (protocol, port) => {
      const err = await protocol.syncWriteTxOnly(port, Registers.TORQUE_ENABLE, 1, data)
      if (err !== 0) throw new Error(`急停失败 (${err})`)
    })
  }
}
