import { Suspense, useRef, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { useGLTF, OrbitControls, Grid, Center, Stage } from '@react-three/drei'
import { useAppStore } from '../store/appStore'
import * as THREE from 'three'

function Model({ url, mode }: { url: string; mode: string }) {
  const { scene } = useGLTF(url)
  const groupRef = useRef<THREE.Group>(null)

  useEffect(() => {
    if (!groupRef.current) return
    groupRef.current.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh
        const mat = mesh.material as THREE.MeshStandardMaterial
        if (mode === 'wireframe') {
          mesh.material = new THREE.MeshBasicMaterial({ wireframe: true, color: '#1a1a1a' })
        } else if (mode === 'solid') {
          mesh.material = new THREE.MeshStandardMaterial({
            color: mat?.color || '#e5e5e5',
            roughness: 0.4,
            metalness: 0.1,
          })
        }
        // texture mode keeps original materials
      }
    })
  }, [mode])

  return (
    <group ref={groupRef}>
      <primitive object={scene} scale={1} />
    </group>
  )
}

function PlaceholderCube() {
  const ref = useRef<THREE.Mesh>(null)
  useFrame((state) => {
    if (ref.current) ref.current.rotation.y = state.clock.elapsedTime * 0.3
  })
  return (
    <mesh ref={ref} position={[0, 0.5, 0]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshBasicMaterial wireframe color="#1a1a1a" />
      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(1, 1, 1)]} />
        <lineBasicMaterial color="#1a1a1a" />
      </lineSegments>
    </mesh>
  )
}

function Turntable() {
  const ref = useRef<THREE.Mesh>(null)
  useFrame((state) => {
    if (ref.current) ref.current.rotation.y = state.clock.elapsedTime * 0.15
  })
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <circleGeometry args={[1.6, 64]} />
      <meshStandardMaterial color="#d4d4d4" roughness={0.6} />
    </mesh>
  )
}

function Axes() {
  return (
    <group position={[-1.6, 0.05, 1.4]}>
      <arrowHelper args={[new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 0), 0.35, '#ef4444', 0.08, 0.04]} />
      <arrowHelper args={[new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 0), 0.35, '#22c55e', 0.08, 0.04]} />
      <arrowHelper args={[new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0, 0), 0.35, '#3b82f6', 0.08, 0.04]} />
    </group>
  )
}

export function ModelTurntable({ modelUrl }: { modelUrl?: string | null }) {
  const rotation = useAppStore((s) => s.rotation)
  const previewMode = useAppStore((s) => s.previewMode)
  const brightness = useAppStore((s) => s.brightness)
  const shadowDensity = useAppStore((s) => s.shadowDensity)

  const intensity = brightness / 50

  return (
    <div className="relative flex h-full flex-col rounded-2xl border border-neutral-300 bg-white/60 p-1">
      <div className="relative flex-1 overflow-hidden rounded-xl bg-gradient-to-br from-neutral-100 to-neutral-200">
        <Canvas camera={{ position: [2.5, 2, 2.5], fov: 35 }} shadows dpr={[1, 2]}>
          <ambientLight intensity={0.6 * intensity} />
          <directionalLight
            position={[5, 8, 5]}
            intensity={1.2 * intensity}
            castShadow
            shadow-mapSize={1024}
          />
          <spotLight position={[-5, 8, -5]} intensity={0.5 * shadowDensity / 50} angle={0.4} />

          <Suspense fallback={null}>
            <Turntable />
            {previewMode === 'printbed' && <Grid cellSize={0.2} infiniteGrid fadeDistance={5} />}
            {modelUrl ? (
              <Stage environment={previewMode === 'texture' ? 'city' : undefined} intensity={0.5} shadows={false}>
                <Center>
                  <Model url={modelUrl} mode={previewMode} />
                </Center>
              </Stage>
            ) : (
              <PlaceholderCube />
            )}
            <Axes />
          </Suspense>

          <OrbitControls autoRotate autoRotateSpeed={1} enablePan={false} minDistance={2} maxDistance={6} />
        </Canvas>

        <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 text-center">
          <p className="text-[10px] uppercase tracking-widest text-neutral-500">Rotation</p>
          <p className="text-xl font-light text-neutral-800">{rotation}°</p>
        </div>
      </div>
    </div>
  )
}
