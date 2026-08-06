#!/usr/bin/env node
/**
 * Feetech WebSerial 协议层冒烟测试（无需硬件）
 *
 * 验证 apps/web/src/lib/webserial.ts 的包构造 / 校验和 / 响应解析是否符合
 * Feetech STS 串口总线规范（Dynamixel 风格，LE 字序）。
 *
 * 运行（仓库根目录）：
 *   node scripts/webserial-protocol-smoke.mjs
 */
import { createRequire } from 'node:module'
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// --- 1. 用 TypeScript 编译器 API 把 TS 模块转译为 ESM（无需 esbuild/vite） ---
const require = createRequire(import.meta.url)
const ts = require(require.resolve('typescript', { paths: ['apps/web'] }))
const outDir = mkdtempSync(join(tmpdir(), 'ws-smoke-'))
const src = readFileSync('apps/web/src/lib/webserial.ts', 'utf8')
const out = ts.transpileModule(src, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
}).outputText
writeFileSync(join(outDir, 'webserial.mjs'), out)
const mod = await import(`file://${join(outDir, 'webserial.mjs')}`)
const { FeetechSerialPort, FeetechProtocol, Registers } = mod

// --- 2. 假端口：捕获写出的包，按「每事务一包」队列喂回读响应 ---
class FakePort extends FeetechSerialPort {
  constructor() {
    super(1_000_000)
    this.isOpen = true
    this.sent = [] // 捕获所有 TX 包
    this.packets = [] // 待喂回的状态包队列（一个事务消费一个）
    this.response = [] // 当前正在切块喂出的包
  }
  queue(packet) {
    this.packets.push(packet)
  }
  async write(packet) {
    this.sent.push([...packet])
    return packet.length
  }
  async read(maxBytes) {
    if (this.response.length === 0 && this.packets.length > 0) {
      this.response = this.packets.shift()
    }
    const take = this.response.slice(0, maxBytes)
    this.response = this.response.slice(take.length)
    return take
  }
}

// 手工按规范构造状态包（仅用于喂假响应，独立于被测实现）
const statusPacket = (id, params) => {
  const pkt = [0xff, 0xff, id, params.length + 2, 0, ...params, 0]
  let s = 0
  for (let i = 2; i < pkt.length - 1; i++) s += pkt[i]
  pkt[pkt.length - 1] = 255 & ~s
  return pkt
}

let pass = 0
let fail = 0
const assert = (name, cond, detail) => {
  if (cond) {
    pass++
    console.log(`  ✓ ${name}`)
  } else {
    fail++
    console.error(`  ✗ ${name} ${detail ?? ''}`)
  }
}
const hex = (a) => a.map((b) => b.toString(16).padStart(2, '0')).join(' ')

console.log('[1] ping 包构造 + 校验和')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  port.queue(statusPacket(1, [])) // PING 响应 [FF FF 01 02 00 FC]
  port.queue(statusPacket(1, [0x01, 0x01])) // 型号读响应（地址 3，2 字节）
  const r = await protocol.ping(port, 1)
  assert('TX = [FF FF 01 02 01 FB]', hex(port.sent[0]) === 'ff ff 01 02 01 fb', hex(port.sent[0]))
  assert('读型号（LE: 0x01 0x01 → 0x0101=257）', r.model === 257, `model=${r.model}`)
  assert('ping 无错误', r.error === 0, `error=${r.error}`)
}

console.log('[2] read2ByteTxRx（Present Position 地址 0x38）')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  port.queue(statusPacket(1, [0x01, 0x02])) // 0x0201 LE
  const [value, error] = await protocol.read2ByteTxRx(port, 1, Registers.PRESENT_POSITION)
  assert('TX = [FF FF 01 04 02 38 02 BE]', hex(port.sent[0]) === 'ff ff 01 04 02 38 02 be', hex(port.sent[0]))
  assert('解析 LE 值 = 0x0201', value === 0x0201, `value=${value}`)
  assert('无错误', error === 0, `error=${error}`)
}

console.log('[3] write2ByteTxRx（Goal Position 地址 0x2A, 值 0x0201）')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  port.queue(statusPacket(1, []))
  const [errno, error] = await protocol.write2ByteTxRx(port, 1, Registers.GOAL_POSITION, 0x0201)
  assert('TX = [FF FF 01 05 03 2A 01 02 C9]', hex(port.sent[0]) === 'ff ff 01 05 03 2a 01 02 c9', hex(port.sent[0]))
  assert('errno=0, error=0', errno === 0 && error === 0, `errno=${errno} error=${error}`)
}

console.log('[4] 广播 ID 254 写被拒绝（安全纪律）')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  const [errno, error] = await protocol.writeTxRx(port, 254, Registers.GOAL_POSITION, [1])
  // 契约 [errno, error]：error=-9 让只查 error 的调用方看到失败（M42 审查 #3 修复）
  assert('返回 [0, -9]', errno === 0 && error === -9, `errno=${errno} error=${error}`)
  assert('未发送任何字节', port.sent.length === 0)
}

console.log('[5] syncReadTx 广播包（IDs 1,2,3，地址 0x38，2 字节）')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  const r = await protocol.syncReadTx(port, 0x38, 2, [1, 2, 3])
  assert(
    'TX = [FF FF FE 07 82 38 02 01 02 03 38]',
    hex(port.sent[0]) === 'ff ff fe 07 82 38 02 01 02 03 38',
    hex(port.sent[0]),
  )
  assert('返回 0', r === 0, `r=${r}`)
}

console.log('[6] 无响应 → 超时错误 -6')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  const [data, error] = await protocol.readTxRx(port, 1, 0x38, 2)
  assert('返回错误 -6', error === -6, `error=${error}`)
  assert('数据为空', data.length === 0)
}

console.log('[7] 特性检测（node 环境应为 false）')
assert('isWebSerialSupported() === false', mod.isWebSerialSupported() === false)

console.log('[7b] 变长读写 + 广播拒绝 + 错误文案')
{
  const port = new FakePort()
  const protocol = new FeetechProtocol()
  // 7b.1 read1Byte：单字节回读
  port.queue(statusPacket(1, [0xab]))
  const [v1, e1] = await protocol.read1ByteTxRx(port, 1, 0x38)
  assert('read1Byte 回读 0xAB', v1 === 0xab && e1 === 0, `v1=${v1} e1=${e1}`)
  // 7b.2 read4Byte：LE 32 位（0x78 56 34 12 → 0x12345678）
  port.queue(statusPacket(1, [0x78, 0x56, 0x34, 0x12]))
  const [v4, e4] = await protocol.read4ByteTxRx(port, 1, 0x38)
  assert('read4Byte LE 值 = 0x12345678', v4 === 0x12345678 && e4 === 0, `v4=0x${v4.toString(16)}`)
  // 7b.3 write1Byte：单字节写包
  port.queue(statusPacket(3, []))
  const [, w1] = await protocol.write1ByteTxRx(port, 3, 0x28, 1)
  assert('write1Byte TX = [FF FF 03 04 03 28 01 CC]', hex(port.sent[2]) === 'ff ff 03 04 03 28 01 cc', hex(port.sent[2]))
  assert('write1Byte 无错误', w1 === 0, `w1=${w1}`)
  // 7b.4 ping 广播 ID 拒绝（安全纪律）
  const p254 = await protocol.ping(port, 254)
  assert('ping(254) 返回 -9 且未发包', p254.error === -9 && port.sent.length === 3, `error=${p254.error}`)
  // 7b.5 错误文案
  assert('txRxResultText(-6) 文案', mod.txRxResultText(-6) === '[TxRxResult] There is no status packet!')
  assert('rxPacketErrorText(1) = 电压错误', mod.rxPacketErrorText(1) === '[RxPacketError] Input voltage error!')
}

console.log('[8] StsSerialBus 高层总线（SO-101 面板 API）')
{
  // 用真实 ReadableStream/WritableStream 伪造 native 串口。
  // 模拟半双工：只有收到某 ID 的写包，才把该 ID 的响应包按序喂回（离线 ID 无响应 → 超时）。
  const makeEnv = (responsesById) => {
    const sentPackets = []
    let controller
    const readable = new ReadableStream({
      start(c) {
        controller = c
      },
    })
    const writable = new WritableStream({
      write(chunk) {
        const pkt = [...chunk]
        sentPackets.push(pkt)
        const queue = responsesById[pkt[2]]
        if (queue && queue.length > 0) controller.enqueue(new Uint8Array(queue.shift()))
      },
    })
    const nativePort = {
      open: async () => {},
      close: async () => {},
      readable,
      writable,
    }
    Object.defineProperty(globalThis, 'navigator', {
      value: { serial: { requestPort: async () => nativePort } },
      configurable: true,
    })
    return { sentPackets }
  }
  const restoreNavigator = () => delete globalThis.navigator

  // 8.1 scan：id 1、3 在线（各需 ping 响应 + 型号读响应），id 2 超时
  {
    const { sentPackets } = makeEnv({
      1: [statusPacket(1, []), statusPacket(1, [0x01, 0x01])],
      3: [statusPacket(3, []), statusPacket(3, [0x01, 0x01])],
    })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    const found = await bus.scan([1, 2, 3])
    assert('scan 找到 [1, 3]', JSON.stringify(found) === '[1,3]', `found=${found}`)
    assert('首发为 PING(1) 包', hex(sentPackets[0]) === 'ff ff 01 02 01 fb', hex(sentPackets[0]))
    assert('共 5 个 TX（2 在线 × 2 + 1 离线 ping）', sentPackets.length === 5, `tx=${sentPackets.length}`)
    await bus.close()
    restoreNavigator()
  }

  // 8.2 readPosition：Present Position 地址 0x38 读回 0x1234
  {
    const { sentPackets } = makeEnv({ 1: [statusPacket(1, [0x34, 0x12])] })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    const pos = await bus.readPosition(1)
    assert('readPosition(1) = 4660 (0x1234)', pos === 4660, `pos=${pos}`)
    assert('TX 为读指令包 [FF FF 01 04 02 38 02 BE]', hex(sentPackets[0]) === 'ff ff 01 04 02 38 02 be', hex(sentPackets[0]))
    await bus.close()
    restoreNavigator()
  }

  // 8.3 writePosition：Goal Position 0x2A 写 0x0201（LE）
  {
    const { sentPackets } = makeEnv({ 2: [statusPacket(2, [])] })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    await bus.writePosition(2, 0x0201)
    assert('TX = [FF FF 02 05 03 2A 01 02 C8]', hex(sentPackets[0]) === 'ff ff 02 05 03 2a 01 02 c8', hex(sentPackets[0]))
    await bus.close()
    restoreNavigator()
  }

  // 8.4 writePosition 钳制：5000 → 4095（0x0FFF）
  {
    const { sentPackets } = makeEnv({ 2: [statusPacket(2, [])] })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    await bus.writePosition(2, 5000)
    // 包结构 [FF FF ID LEN INST ADDR lo hi CHK] — 数据在 index 6..7
    assert('5000 钳制为 4095（数据字节 FF 0F）', sentPackets[0][6] === 0xff && sentPackets[0][7] === 0x0f, hex(sentPackets[0]))
    await bus.close()
    restoreNavigator()
  }

  // 8.5 setTorque：Torque Enable 0x28 写 1
  {
    const { sentPackets } = makeEnv({ 3: [statusPacket(3, [])] })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    await bus.setTorque(3, true)
    assert('TX = [FF FF 03 04 03 28 01 CC]', hex(sentPackets[0]) === 'ff ff 03 04 03 28 01 cc', hex(sentPackets[0]))
    await bus.close()
    restoreNavigator()
  }

  // 8.6 writePositionsMany：一条 0x83 广播包同步写 3 个电机（count=2，不碰 GOAL_TIME）
  {
    const { sentPackets } = makeEnv({})
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    await bus.writePositionsMany([
      { id: 1, value: 0x0201 },
      { id: 2, value: 2048 },
      { id: 3, value: 4095 },
    ])
    assert(
      'TX = [FF FF FE 0D 83 2A 02 …3 电机×3 字节… 26]（count=2，无第 4 字节）',
      hex(sentPackets[0]) === 'ff ff fe 0d 83 2a 02 01 01 02 02 00 08 03 ff 0f 26',
      hex(sentPackets[0]),
    )
    await bus.close()
    restoreNavigator()
  }

  // 8.7 emergencyStop：广播关扭矩（每电机 [ID, 0]）
  {
    const { sentPackets } = makeEnv({})
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    await bus.emergencyStop([1, 2])
    assert(
      'TX = [FF FF FE 08 83 28 01 01 00 02 00 4A]（TORQUE_ENABLE=0 广播）',
      hex(sentPackets[0]) === 'ff ff fe 08 83 28 01 01 00 02 00 4a',
      hex(sentPackets[0]),
    )
    await bus.close()
    restoreNavigator()
  }

  // 8.8 pending read 复用（M42 死锁修复）：无响应事务后，后续事务仍正常
  {
    // id 1 需要两个响应（PING 响应 + 型号读响应）
    const { sentPackets } = makeEnv({
      1: [statusPacket(1, []), statusPacket(1, [0x01, 0x01])],
    })
    const bus = new mod.StsSerialBus()
    await bus.requestAndOpen()
    const found = await bus.scan([2, 1]) // 2 无响应（超时）→ 1 在线；若死锁则 [2,1] 全失败
    assert('超时后事务仍工作（无死锁），scan 找到 [1]', JSON.stringify(found) === '[1]', `found=${found}`)
    assert('共 3 个 TX（ping2 + ping1 + 型号读1）', sentPackets.length === 3, `tx=${sentPackets.length}`)
    await bus.close()
    restoreNavigator()
  }
}

rmSync(outDir, { recursive: true, force: true })
console.log(`\n结果: ${pass} passed, ${fail} failed`)
process.exit(fail > 0 ? 1 : 0)
