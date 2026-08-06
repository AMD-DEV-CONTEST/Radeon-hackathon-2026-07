import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, TransformControls } from '@react-three/drei'
import * as THREE from 'three'
import { loadURDF, hideLinkVisualsMany } from '../../lib/urdf'
import {
  clampPose,
  type ReachyEditPart,
  type ReachyPoseFrame,
} from '../../lib/reachyMotionClip'
import {
  applyReachyEditorDisplayPose,
  getReachyBodyLink,
  getReachyHeadLink,
  REACHY_MINI_HIDDEN_LINKS,
} from '../../lib/reachyVirtualPreview'

export type { ReachyEditPart }

function RobotNode({
  robot,
  pose,
}: {
  robot: THREE.Group | null
  pose: ReachyPoseFrame
}) {
  useFrame(() => {
    if (robot) applyReachyEditorDisplayPose(robot, pose)
  })
  if (!robot) return null
  return <primitive object={robot} />
}

function HeadGizmo({
  robot,
  pose,
  active,
  onPoseChange,
  onDraggingChange,
}: {
  robot: THREE.Group
  pose: ReachyPoseFrame
  active: boolean
  onPoseChange: (pose: ReachyPoseFrame) => void
  onDraggingChange: (dragging: boolean) => void
}) {
  const helperRef = useRef<THREE.Object3D>(null!)
  const draggingRef = useRef(false)

  // Keep the gizmo at the head's world position; orientation = body frame * commanded RPY.
  // The helper is an INDEPENDENT command frame (not read back from the deformed legs),
  // so dragging maps 1:1 to head RPY regardless of the Stewart approximation.
  useFrame(() => {
    const head = getReachyHeadLink(robot)
    const body = getReachyBodyLink(robot)
    if (!head || !body || !helperRef.current || draggingRef.current) return
    head.updateWorldMatrix(true, true)
    body.updateWorldMatrix(true, true)
    head.getWorldPosition(helperRef.current.position)
    const bodyQ = new THREE.Quaternion()
    body.getWorldQuaternion(bodyQ)
    const deltaQ = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(pose.head.roll, pose.head.pitch, pose.head.yaw, 'ZYX'),
    )
    helperRef.current.quaternion.copy(bodyQ).multiply(deltaQ)
  })

  const emitFromHelper = useCallback(() => {
    const body = getReachyBodyLink(robot)
    if (!body || !helperRef.current) return
    body.updateWorldMatrix(true, true)
    const bodyQ = new THREE.Quaternion()
    body.getWorldQuaternion(bodyQ)
    const localQ = bodyQ.clone().invert().multiply(helperRef.current.quaternion)
    const e = new THREE.Euler().setFromQuaternion(localQ, 'ZYX')
    onPoseChange(clampPose({
      ...pose,
      head: { roll: e.x, pitch: e.y, yaw: e.z },
    }))
  }, [onPoseChange, pose, robot])

  return (
    <>
      <object3D ref={helperRef} />
      {active && (
        <TransformControls
          object={helperRef}
          mode="rotate"
          size={0.85}
          onMouseDown={() => {
            draggingRef.current = true
            onDraggingChange(true)
          }}
          onMouseUp={() => {
            draggingRef.current = false
            onDraggingChange(false)
            emitFromHelper()
          }}
          onObjectChange={() => {
            if (!draggingRef.current) return
            emitFromHelper()
          }}
        />
      )}
    </>
  )
}

function BodyGizmo() {
  return null
}

function SceneContent({
  urdfUrl,
  displayPose,
  editPose,
  onPoseChange,
  selectedPart,
  onDraggingChange,
  orbitTarget,
  orbitEnabled,
}: {
  urdfUrl: string
  displayPose: ReachyPoseFrame
  editPose: ReachyPoseFrame
  onPoseChange: (pose: ReachyPoseFrame) => void
  selectedPart: ReachyEditPart
  onDraggingChange: (dragging: boolean) => void
  orbitTarget: [number, number, number]
  orbitEnabled: boolean
}) {
  const [robot, setRobot] = useState<THREE.Group | null>(null)

  useEffect(() => {
    let cancelled = false
    loadURDF(urdfUrl, { eagerDisplay: true })
      .then(({ robot: r }) => {
        if (cancelled) return
        hideLinkVisualsMany(r, REACHY_MINI_HIDDEN_LINKS)
        setRobot(r)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [urdfUrl])

  return (
    <>
      <ambientLight intensity={0.7} />
      <directionalLight position={[2, 3, 2]} intensity={0.9} />
      <directionalLight position={[-1, 2, -1]} intensity={0.35} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
        <planeGeometry args={[2.5, 2.5]} />
        <meshStandardMaterial color="#1e293b" />
      </mesh>
      <RobotNode robot={robot} pose={displayPose} />
      {robot && (
        <>
          <HeadGizmo
            robot={robot}
            pose={editPose}
            active={selectedPart === 'head'}
            onPoseChange={onPoseChange}
            onDraggingChange={onDraggingChange}
          />
          <BodyGizmo />
        </>
      )}
      <OrbitControls
        target={orbitTarget}
        enableDamping
        dampingFactor={0.08}
        enabled={orbitEnabled}
        minDistance={0.15}
        maxDistance={1.2}
      />
    </>
  )
}

export interface ReachyInteractiveViewerProps {
  urdfUrl?: string
  displayPose: ReachyPoseFrame
  editPose: ReachyPoseFrame
  onPoseChange: (pose: ReachyPoseFrame) => void
  selectedPart: ReachyEditPart
  className?: string
  cameraPosition?: [number, number, number]
  orbitTarget?: [number, number, number]
}

function ReachyInteractiveViewerInner({
  urdfUrl = '/api/urdf/reachy_mini/reachy_mini.urdf',
  displayPose,
  editPose,
  onPoseChange,
  selectedPart,
  className,
  cameraPosition = [0.22, 0.28, 0.38],
  orbitTarget = [0, 0.12, 0],
}: ReachyInteractiveViewerProps) {
  const [dragging, setDragging] = useState(false)

  return (
    <div className={className ?? 'relative w-full h-full min-h-[400px] overflow-hidden bg-[#0b0f1a]'}>
      <Canvas
        camera={{ position: cameraPosition, fov: 45, near: 0.01, far: 50 }}
        frameloop="always"
        dpr={[1, 2]}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        style={{ width: '100%', height: '100%' }}
      >
        <SceneContent
          urdfUrl={urdfUrl}
          displayPose={displayPose}
          editPose={editPose}
          onPoseChange={onPoseChange}
          selectedPart={selectedPart}
          onDraggingChange={setDragging}
          orbitTarget={orbitTarget}
          orbitEnabled={!dragging}
        />
      </Canvas>
    </div>
  )
}

export const ReachyInteractiveViewer = memo(ReachyInteractiveViewerInner)
