import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Excalidraw } from '@excalidraw/excalidraw'

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const BACKEND_URL = '' // 同源部署，空字符串 = 相对路径

const STYLES = [
  { key: 'cyberpunk', label: 'Cyberpunk' },
  { key: 'anime', label: 'Anime' },
  { key: 'watercolor', label: 'Watercolor' },
  { key: 'oil_painting', label: 'Oil Painting' },
  { key: '3d_render', label: '3D Render' },
  { key: 'pixel_art', label: 'Pixel Art' },
  { key: 'concept_art', label: 'Concept Art' },
  { key: 'minimalist', label: 'Minimalist' },
]

const RATIOS_FAST = [
  { key: '1:1', label: '1:1' },
  { key: '3:4', label: '3:4' },
  { key: '4:3', label: '4:3' },
  { key: '3:2', label: '3:2' },
  { key: '16:9', label: '16:9' },
]

// ---------------------------------------------------------------------------
// 主应用
// ---------------------------------------------------------------------------

export default function App() {
  const [mode, setMode] = useState('fast') // fast | expert
  const [selectedStyle, setSelectedStyle] = useState('cyberpunk')
  const [selectedRatio, setSelectedRatio] = useState('1:1')
  const [showStylePanel, setShowStylePanel] = useState(false)
  const [showLoraPanel, setShowLoraPanel] = useState(false)
  const [showParamPanel, setShowParamPanel] = useState(false)
  const [nodes, setNodes] = useState([]) // {id, type, x, y, prompt, image, generating, error}
  const [nodeCounter, setNodeCounter] = useState(1)
  const [strength, setStrength] = useState(0.8)

  // Expert 参数
  const [steps, setSteps] = useState(4)
  const [cfg, setCfg] = useState(1.5)
  const [seed, setSeed] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')

  // LoRA
  const [loras, setLoras] = useState([]) // {id, path, weight, name}

  const excalidrawRef = useRef(null)
  const setExcalidrawAPI = useCallback((api) => {
    excalidrawRef.current = api
  }, [])

  // 初始化：创建一个默认文生图节点
  useEffect(() => {
    if (nodes.length === 0) {
      addNode('text', 100, 100)
    }
  }, []) // eslint-disable-line

  // ------------------------------------------------------------------
  // 节点操作
  // ------------------------------------------------------------------

  const addNode = useCallback((type = 'text', x = 200, y = 200) => {
    const id = `node-${nodeCounter}`
    setNodeCounter(c => c + 1)
    const newNode = {
      id,
      type, // 'text' | 'sketch'
      x,
      y,
      prompt: '',
      image: null,
      generating: false,
      error: null,
    }
    setNodes(prev => [...prev, newNode])
    return id
  }, [nodeCounter])

  const updateNode = useCallback((id, updates) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, ...updates } : n))
  }, [])

  const deleteNode = useCallback((id) => {
    setNodes(prev => prev.filter(n => n.id !== id))
  }, [])

  // ------------------------------------------------------------------
  // 生成
  // ------------------------------------------------------------------

  const generateForNode = useCallback(async (nodeId) => {
    const node = nodes.find(n => n.id === nodeId)
    if (!node) return

    updateNode(nodeId, { generating: true, error: null, image: null })

    try {
      let resultImage
      const style = selectedStyle
      const aspect_ratio = selectedRatio

      if (node.type === 'text') {
        // 文生图
        const body = {
          prompt: node.prompt || 'a beautiful scene',
          mode,
          style,
          aspect_ratio,
        }
        if (mode === 'expert') {
          body.num_inference_steps = steps
          body.guidance_scale = cfg
          if (seed) body.seed = parseInt(seed)
          if (negativePrompt) body.negative_prompt = negativePrompt
          if (loras.length > 0) {
            body.loras = loras.map(l => l.path)
            body.lora_weights = loras.map(l => l.weight)
          }
        }

        const resp = await fetch(`${BACKEND_URL}/api/generate/text2img`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!resp.ok) {
          const err = await resp.json()
          throw new Error(err.detail || 'Generation failed')
        }
        const data = await resp.json()
        resultImage = data.image
      } else {
        // 草图节点 (img2img) — 从 Excalidraw 画布导出
        const api = excalidrawRef.current
        if (!api) throw new Error('Canvas not ready')

        const { exportToBlob } = await import('@excalidraw/excalidraw')
        const elements = api.getSceneElements()
        const appState = api.getAppState()
        const files = api.getFiles()

        const blob = await exportToBlob({
          elements,
          appState: { ...appState, exportBackground: true },
          files,
          mimeType: 'image/png',
          quality: 1.0,
        })

        const formData = new FormData()
        formData.append('file', blob, 'sketch.png')
        formData.append('mode', mode)
        formData.append('style', style)
        formData.append('aspect_ratio', aspect_ratio)
        formData.append('strength', strength.toString())

        if (mode === 'expert') {
          formData.append('num_inference_steps', steps)
          formData.append('guidance_scale', cfg)
          if (seed) formData.append('seed', seed)
          if (negativePrompt) formData.append('negative_prompt', negativePrompt)
          if (loras.length > 0) {
            formData.append('loras', loras.map(l => l.path).join(','))
            formData.append('lora_weights', loras.map(l => l.weight).join(','))
          }
        }

        const resp = await fetch(`${BACKEND_URL}/api/generate/img2img`, {
          method: 'POST',
          body: formData,
        })
        if (!resp.ok) {
          const err = await resp.json()
          throw new Error(err.detail || 'Generation failed')
        }
        const data = await resp.json()
        resultImage = data.image
      }

      updateNode(nodeId, { generating: false, image: resultImage })
    } catch (e) {
      updateNode(nodeId, { generating: false, error: e.message })
    }
  }, [nodes, selectedStyle, selectedRatio, mode, steps, cfg, seed, negativePrompt, loras, strength, updateNode])

  // ------------------------------------------------------------------
  // LoRA 管理
  // ------------------------------------------------------------------

  const addLora = useCallback((path, weight = 0.8) => {
    const id = `lora-${Date.now()}`
    const name = path.split('/').pop() || path
    setLoras(prev => [...prev, { id, path, weight, name }])
  }, [])

  const updateLoraWeight = useCallback((id, weight) => {
    setLoras(prev => prev.map(l => l.id === id ? { ...l, weight } : l))
  }, [])

  const removeLora = useCallback((id) => {
    setLoras(prev => prev.filter(l => l.id !== id))
  }, [])

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------

  return (
    <div style={{
      width: '100vw', height: '100vh',
      display: 'flex', flexDirection: 'column',
      background: '#fafafa',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      overflow: 'hidden',
    }}>
      {/* ========== 顶栏 ========== */}
      <div style={{
        height: '56px', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 24px',
        background: '#fff',
        borderBottom: '1px solid #e5e5e5',
      }}>
        {/* 左侧品牌 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '32px', height: '32px',
            background: '#000', borderRadius: '6px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontWeight: 700, fontSize: '14px',
          }}>N</div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, color: '#111' }}>NodeFlow</div>
            <div style={{ fontSize: '10px', color: '#999', letterSpacing: '0.5px' }}>AI CANVAS</div>
          </div>
        </div>

        {/* 中央模式切换 */}
        <div style={{
          display: 'flex', gap: '2px',
          background: '#f0f0f0', borderRadius: '8px',
          padding: '3px',
        }}>
          <button
            onClick={() => setMode('fast')}
            style={{
              padding: '6px 24px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '13px', fontWeight: 600,
              background: mode === 'fast' ? '#fff' : 'transparent',
              color: mode === 'fast' ? '#111' : '#666',
              boxShadow: mode === 'fast' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              transition: 'all 0.15s',
            }}
          >
            Fast
          </button>
          <button
            onClick={() => setMode('expert')}
            style={{
              padding: '6px 24px',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '13px', fontWeight: 600,
              background: mode === 'expert' ? '#fff' : 'transparent',
              color: mode === 'expert' ? '#111' : '#666',
              boxShadow: mode === 'expert' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              transition: 'all 0.15s',
            }}
          >
            Expert
          </button>
        </div>

        {/* 右侧图标 */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button style={iconBtnStyle}>History</button>
          <button style={iconBtnStyle}>Settings</button>
          <button style={iconBtnStyle}>Store</button>
        </div>
      </div>

      {/* ========== 主画布区 ========== */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {/* Excalidraw 画布 */}
        <div style={{ position: 'absolute', inset: 0 }}>
          <Excalidraw
            excalidrawAPI={setExcalidrawAPI}
            initialData={{ elements: [] }}
            UIOptions={{
              canvasActions: {
                loadScene: false,
                saveToActiveFile: false,
                export: false,
                toggleTheme: false,
              },
            }}
            theme="light"
          />
        </div>

        {/* 节点层 (覆盖在画布上方) */}
        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
          {nodes.map(node => (
            <NodeCard
              key={node.id}
              node={node}
              mode={mode}
              onUpdate={(updates) => updateNode(node.id, updates)}
              onDelete={() => deleteNode(node.id)}
              onGenerate={() => generateForNode(node.id)}
              onAddTextNode={() => addNode('text', node.x + 320, node.y)}
              strength={strength}
              onStrengthChange={setStrength}
            />
          ))}
        </div>

        {/* 空态提示 */}
        {nodes.length === 0 && (
          <div style={{
            position: 'absolute', top: '50%', left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center', color: '#999',
            pointerEvents: 'none',
          }}>
            <div style={{ fontSize: '18px', marginBottom: '8px' }}>✨ 开始创作</div>
            <div style={{ fontSize: '13px' }}>添加节点，连接灵感</div>
          </div>
        )}

        {/* 添加节点按钮 (左下) */}
        <div style={{
          position: 'absolute', left: '20px', bottom: '80px',
          display: 'flex', flexDirection: 'column', gap: '8px',
          pointerEvents: 'auto',
        }}>
          <button
            onClick={() => addNode('text')}
            style={{
              ...iconBtnStyle,
              width: '40px', height: '40px',
              borderRadius: '8px',
              fontSize: '18px',
              background: '#fff',
              border: '1px solid #ddd',
              boxShadow: '0 2px 6px rgba(0,0,0,0.08)',
            }}
            title="添加文生图节点"
          >
            ＋
          </button>
          <button
            onClick={() => addNode('sketch')}
            style={{
              ...iconBtnStyle,
              width: '40px', height: '40px',
              borderRadius: '8px',
              fontSize: '14px',
              background: '#fff',
              border: '1px solid #ddd',
              boxShadow: '0 2px 6px rgba(0,0,0,0.08)',
            }}
            title="添加草图节点"
          >
            ✎
          </button>
        </div>
      </div>

      {/* ========== 底部控制坞 ========== */}
      <div style={{
        position: 'absolute', bottom: '20px', left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex', alignItems: 'center', gap: '4px',
        padding: '8px 12px',
        background: 'rgba(255, 255, 255, 0.95)',
        backdropFilter: 'blur(10px)',
        border: '1px solid #e5e5e5',
        borderRadius: '12px',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.1)',
        pointerEvents: 'auto',
        zIndex: 100,
      }}>
        {/* 风格选择 */}
        <button
          onClick={() => { setShowStylePanel(!showStylePanel); setShowLoraPanel(false); setShowParamPanel(false); }}
          style={dockBtnStyle}
        >
          🎨 {STYLES.find(s => s.key === selectedStyle)?.label || 'Style'}
        </button>

        <div style={dockDivider} />

        {/* 比例选择 */}
        <div style={{ display: 'flex', gap: '4px' }}>
          {RATIOS_FAST.map(r => (
            <button
              key={r.key}
              onClick={() => setSelectedRatio(r.key)}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '12px', fontWeight: 500,
                background: selectedRatio === r.key ? '#111' : 'transparent',
                color: selectedRatio === r.key ? '#fff' : '#555',
                transition: 'all 0.15s',
              }}
            >
              {r.label}
            </button>
          ))}
        </div>

        {mode === 'expert' && (
          <>
            <div style={dockDivider} />
            <button onClick={() => { setShowParamPanel(!showParamPanel); setShowStylePanel(false); setShowLoraPanel(false); }} style={dockBtnStyle}>
              ⚙ Parameters
            </button>
            <div style={dockDivider} />
            <button onClick={() => { setShowLoraPanel(!showLoraPanel); setShowStylePanel(false); setShowParamPanel(false); }} style={dockBtnStyle}>
              🧩 LoRA {loras.length > 0 && `(${loras.length})`}
            </button>
          </>
        )}

        <div style={dockDivider} />

        <button
          onClick={() => nodes.length > 0 && generateForNode(nodes[nodes.length - 1].id)}
          style={{
            ...dockBtnStyle,
            background: '#111',
            color: '#fff',
            padding: '8px 24px',
            fontWeight: 600,
          }}
        >
          Generate →
        </button>
      </div>

      {/* ========== 风格面板弹窗 ========== */}
      {showStylePanel && (
        <PanelOverlay onClose={() => setShowStylePanel(false)} title="Style Preset">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
            {STYLES.map(s => (
              <button
                key={s.key}
                onClick={() => { setSelectedStyle(s.key); setShowStylePanel(false); }}
                style={{
                  padding: '16px 12px',
                  borderRadius: '8px',
                  border: selectedStyle === s.key ? '2px solid #111' : '1px solid #ddd',
                  background: selectedStyle === s.key ? '#f5f5f5' : '#fff',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: selectedStyle === s.key ? 600 : 400,
                  textAlign: 'center',
                  transition: 'all 0.15s',
                }}
              >
                {s.label}
              </button>
            ))}
          </div>
        </PanelOverlay>
      )}

      {/* ========== 参数面板 (Expert) ========== */}
      {showParamPanel && mode === 'expert' && (
        <PanelOverlay onClose={() => setShowParamPanel(false)} title="Parameters">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <SliderField
              label="Steps" value={steps} min={1} max={100} step={1}
              onChange={setSteps}
            />
            <SliderField
              label="CFG Scale" value={cfg} min={0} max={20} step={0.5}
              onChange={setCfg}
            />
            <div>
              <label style={fieldLabelStyle}>Seed</label>
              <input
                type="number"
                value={seed}
                onChange={e => setSeed(e.target.value)}
                placeholder="随机"
                style={{
                  width: '100%', padding: '8px 12px',
                  border: '1px solid #ddd', borderRadius: '6px',
                  fontSize: '13px',
                }}
              />
            </div>
            <div>
              <label style={fieldLabelStyle}>Negative Prompt</label>
              <textarea
                value={negativePrompt}
                onChange={e => setNegativePrompt(e.target.value)}
                placeholder="低质量、模糊..."
                rows={3}
                style={{
                  width: '100%', padding: '8px 12px',
                  border: '1px solid #ddd', borderRadius: '6px',
                  fontSize: '13px', resize: 'vertical',
                  fontFamily: 'inherit',
                }}
              />
            </div>
          </div>
        </PanelOverlay>
      )}

      {/* ========== LoRA 面板 (Expert) ========== */}
      {showLoraPanel && mode === 'expert' && (
        <PanelOverlay onClose={() => setShowLoraPanel(false)} title="LoRA Manager" width={420}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* 已加载 LoRA */}
            <div>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#666', marginBottom: '8px' }}>
                LOADED ({loras.length})
              </div>
              {loras.length === 0 ? (
                <div style={{
                  padding: '20px', textAlign: 'center',
                  border: '1px dashed #ddd', borderRadius: '8px',
                  fontSize: '12px', color: '#999',
                }}>
                  暂未加载 LoRA
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {loras.map(l => (
                    <div key={l.id} style={{
                      padding: '10px 12px',
                      background: '#f9f9f9',
                      borderRadius: '6px',
                      border: '1px solid #eee',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 500, color: '#333' }}>{l.name}</span>
                        <button
                          onClick={() => removeLora(l.id)}
                          style={{
                            fontSize: '11px', color: '#999',
                            background: 'none', border: 'none',
                            cursor: 'pointer',
                          }}
                        >
                          ✕
                        </button>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <input
                          type="range" min={0} max={2} step={0.1}
                          value={l.weight}
                          onChange={e => updateLoraWeight(l.id, parseFloat(e.target.value))}
                          style={{ flex: 1 }}
                        />
                        <span style={{ fontSize: '11px', color: '#666', width: '36px', textAlign: 'right' }}>
                          {l.weight.toFixed(1)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 快速添加 */}
            <div>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#666', marginBottom: '8px' }}>
                QUICK ADD (SDXL)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                {['sdxl_detail_tweaker', 'sdxl_cyberpunk', 'sdxl_anime', 'sdxl_watercolor', 'sdxl_oil_painting', 'sdxl_3d_render', 'sdxl_pixel_art', 'sdxl_concept_art'].map(id => {
                  const name = id.replace('sdxl_', '').replace(/_/g, ' ')
                  const path = `/persistent/loras/sdxl/${id.replace('sdxl_', '')}.safetensors`
                  const loaded = loras.some(l => l.path === path)
                  return (
                    <button
                      key={id}
                      onClick={() => !loaded && addLora(path, 0.8)}
                      disabled={loaded}
                      style={{
                        padding: '8px',
                        borderRadius: '6px',
                        border: loaded ? '1px solid #ddd' : '1px solid #ccc',
                        background: loaded ? '#f0f0f0' : '#fff',
                        cursor: loaded ? 'default' : 'pointer',
                        fontSize: '11px',
                        color: loaded ? '#999' : '#333',
                        textTransform: 'capitalize',
                      }}
                    >
                      {loaded ? '✓ ' : '+ '}{name}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </PanelOverlay>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 节点卡片组件
// ---------------------------------------------------------------------------

function NodeCard({ node, mode, onUpdate, onDelete, onGenerate, strength, onStrengthChange }) {
  const isText = node.type === 'text'

  return (
    <div
      style={{
        position: 'absolute',
        left: node.x,
        top: node.y,
        width: '300px',
        background: '#fff',
        border: '1px solid #e5e5e5',
        borderRadius: '10px',
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.08)',
        pointerEvents: 'auto',
        overflow: 'hidden',
      }}
    >
      {/* 节点头部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px',
        background: '#fafafa',
        borderBottom: '1px solid #eee',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            fontSize: '10px', fontWeight: 600,
            padding: '2px 8px', borderRadius: '4px',
            background: isText ? '#e8f5e9' : '#fff3e0',
            color: isText ? '#2e7d32' : '#e65100',
            letterSpacing: '0.5px',
          }}>
            {isText ? 'TEXT' : 'SKETCH'}
          </span>
          <span style={{ fontSize: '11px', color: '#999' }}>{node.id}</span>
        </div>
        <button
          onClick={onDelete}
          style={{
            background: 'none', border: 'none',
            cursor: 'pointer', color: '#999',
            fontSize: '14px',
          }}
        >
          ✕
        </button>
      </div>

      {/* 节点内容 */}
      <div style={{ padding: '12px' }}>
        {isText ? (
          // 文生图节点
          <textarea
            value={node.prompt}
            onChange={e => onUpdate({ prompt: e.target.value })}
            placeholder="描述你想生成的画面..."
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                onGenerate()
              }
            }}
            style={{
              width: '100%', minHeight: '80px',
              padding: '10px',
              border: '1px solid #ddd', borderRadius: '6px',
              fontSize: '13px', resize: 'vertical',
              fontFamily: 'inherit',
              outline: 'none',
            }}
          />
        ) : (
          // 草图节点
          <div style={{
            height: '100px',
            background: '#fafafa',
            border: '1px dashed #ddd',
            borderRadius: '6px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '12px', color: '#999',
          }}>
            在画布上绘制草图
          </div>
        )}

        {/* 强度滑杆 (仅草图节点) */}
        {!isText && (
          <div style={{ marginTop: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontSize: '11px', color: '#666' }}>Strength</span>
              <span style={{ fontSize: '11px', color: '#666' }}>{strength.toFixed(1)}</span>
            </div>
            <input
              type="range" min={0.1} max={1} step={0.1}
              value={strength}
              onChange={e => onStrengthChange(parseFloat(e.target.value))}
              style={{ width: '100%' }}
            />
          </div>
        )}

        {/* 生成结果 */}
        {node.image && (
          <div style={{ marginTop: '10px' }}>
            <img
              src={node.image}
              alt="Generated"
              style={{ width: '100%', borderRadius: '6px', display: 'block' }}
            />
          </div>
        )}

        {/* 错误提示 */}
        {node.error && (
          <div style={{
            marginTop: '10px', padding: '8px 10px',
            background: '#fee', color: '#c33',
            fontSize: '12px', borderRadius: '6px',
          }}>
            {node.error}
          </div>
        )}

        {/* 生成按钮 */}
        <button
          onClick={onGenerate}
          disabled={node.generating}
          style={{
            width: '100%', marginTop: '10px',
            padding: '10px',
            borderRadius: '6px',
            border: 'none',
            background: node.generating ? '#ccc' : '#111',
            color: '#fff',
            fontSize: '13px', fontWeight: 600,
            cursor: node.generating ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {node.generating ? 'Generating...' : 'Generate'}
        </button>
      </div>

      {/* 输入输出端口 */}
      <div style={{
        position: 'absolute', left: '-5px', top: '50%',
        width: '10px', height: '10px',
        background: '#fff',
        border: '2px solid #999',
        borderRadius: '50%',
        transform: 'translateY(-50%)',
      }} />
      <div style={{
        position: 'absolute', right: '-5px', top: '50%',
        width: '10px', height: '10px',
        background: '#111',
        border: '2px solid #111',
        borderRadius: '50%',
        transform: 'translateY(-50%)',
      }} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 面板弹窗组件
// ---------------------------------------------------------------------------

function PanelOverlay({ children, onClose, title, width = 360 }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0, 0, 0, 0.3)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: `${width}px`,
          maxHeight: '80vh',
          overflow: 'auto',
          background: '#fff',
          borderRadius: '12px',
          boxShadow: '0 10px 40px rgba(0, 0, 0, 0.2)',
          padding: '20px',
        }}
      >
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: '16px',
        }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, margin: 0 }}>{title}</h3>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none',
              cursor: 'pointer', fontSize: '16px', color: '#999',
            }}
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 通用组件
// ---------------------------------------------------------------------------

function SliderField({ label, value, min, max, step, onChange }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
        <label style={fieldLabelStyle}>{label}</label>
        <span style={{ fontSize: '12px', color: '#666' }}>{value}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        style={{ width: '100%' }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 样式常量
// ---------------------------------------------------------------------------

const iconBtnStyle = {
  padding: '6px 12px',
  borderRadius: '6px',
  border: 'none',
  background: 'transparent',
  cursor: 'pointer',
  fontSize: '13px',
  color: '#555',
  transition: 'background 0.15s',
}

const dockBtnStyle = {
  padding: '6px 14px',
  borderRadius: '6px',
  border: 'none',
  background: 'transparent',
  cursor: 'pointer',
  fontSize: '12px',
  color: '#333',
  whiteSpace: 'nowrap',
  transition: 'background 0.15s',
}

const dockDivider = {
  width: '1px',
  height: '20px',
  background: '#e5e5e5',
}

const fieldLabelStyle = {
  fontSize: '12px',
  fontWeight: 600,
  color: '#555',
  display: 'block',
  marginBottom: '6px',
}
