/**
 * URDF 加载器 (TS 端口, 移植自 V2 apps/realtime/static/urdf_loader.js).
 *
 * 约定:
 *   - URDF 坐标系 Z-up, Three.js 是 Y-up. 在 robotGroup 外层绕 X 旋转 -90° 适配.
 *   - joint 的 THREE.Group 名字就是 URDF joint name (例如 "1"~"6"), 便于
 *     updateRobotJoints 用 getObjectByName 拿到后设 quaternion.
 */

import * as THREE from 'three'
import { STLLoader } from 'three-stdlib'

export interface JointInfo {
  type: string
  parent: string
  child: string
  axis: THREE.Vector3
  limits: { lower: number; upper: number }
}

export interface LoadedURDF {
  robot: THREE.Group
  jointMap: Record<string, JointInfo>
  /** Resolves when all STL meshes have been applied (if any). */
  meshesReady: Promise<void>
}

export interface LoadURDFOptions {
  /** Show link/joint tree before all STLs finish (default true). */
  eagerDisplay?: boolean
  /** Max parallel STL fetches (default 6). */
  meshConcurrency?: number
  onMeshProgress?: (loaded: number, total: number) => void
  /** Called when an STL mesh fails to load (instead of silent tiny box fallback). */
  onMeshFailed?: (meshUrl: string, error: unknown) => void
}

const stlLoader = new STLLoader()
const stlCache = new Map<string, THREE.BufferGeometry>()
const stlPending = new Map<string, Promise<THREE.BufferGeometry>>()
const urdfTextCache = new Map<string, string>()

const DEFAULT_MESH_CONCURRENCY = 6

async function fetchUrdfText(urdfUrl: string): Promise<string> {
  const cached = urdfTextCache.get(urdfUrl)
  if (cached) return cached
  const resp = await fetch(urdfUrl)
  if (!resp.ok) throw new Error(`Failed to fetch URDF: ${resp.status}`)
  const text = await resp.text()
  urdfTextCache.set(urdfUrl, text)
  return text
}

async function loadSTL(url: string): Promise<THREE.BufferGeometry> {
  let master = stlCache.get(url)
  if (!master) {
    let pending = stlPending.get(url)
    if (!pending) {
      pending = (async () => {
        let resp = await fetch(url)
        if (!resp.ok) {
          const alt = url.endsWith('.STL')
            ? url.slice(0, -4) + '.stl'
            : url.endsWith('.stl')
              ? url.slice(0, -4) + '.STL'
              : null
          if (alt) resp = await fetch(alt)
        }
        if (!resp.ok) throw new Error(`STL fetch failed: ${resp.status} ${url}`)
        const buffer = await resp.arrayBuffer()
        const geometry = stlLoader.parse(buffer)
        geometry.computeVertexNormals()
        stlCache.set(url, geometry)
        return geometry
      })().finally(() => stlPending.delete(url))
      stlPending.set(url, pending)
    }
    master = await pending
  }
  // Each viewer instance owns its clone; unmount dispose must not kill the cache master.
  return master.clone()
}

/** Drop cached STL geometry (e.g. after WebGL context lost). */
export function clearStlCache(urlPrefix?: string) {
  if (!urlPrefix) {
    for (const geom of stlCache.values()) geom.dispose()
    stlCache.clear()
    stlPending.clear()
    return
  }
  for (const key of [...stlCache.keys()]) {
    if (key.includes(urlPrefix)) {
      stlCache.get(key)?.dispose()
      stlCache.delete(key)
    }
  }
}

async function runPool<T>(tasks: Array<() => Promise<T>>, concurrency: number): Promise<T[]> {
  if (tasks.length === 0) return []
  const limit = Math.max(1, Math.min(concurrency, tasks.length))
  const results: T[] = new Array(tasks.length)
  let next = 0

  async function worker() {
    while (true) {
      const index = next
      next += 1
      if (index >= tasks.length) return
      results[index] = await tasks[index]()
    }
  }

  await Promise.all(Array.from({ length: limit }, () => worker()))
  return results
}

function parseVec3(str: string | null | undefined, fallback = [0, 0, 0]): THREE.Vector3 {
  if (!str) return new THREE.Vector3(fallback[0], fallback[1], fallback[2])
  const p = str.trim().split(/\s+/).map(parseFloat)
  return new THREE.Vector3(p[0] ?? fallback[0], p[1] ?? fallback[1], p[2] ?? fallback[2])
}

function parseColor(rgba: string | null | undefined): { color: THREE.Color; opacity: number } {
  if (!rgba) return { color: new THREE.Color(0xbbbbbb), opacity: 1 }
  const p = rgba.trim().split(/\s+/).map(parseFloat)
  return {
    color: new THREE.Color(p[0] ?? 1, p[1] ?? 1, p[2] ?? 1),
    opacity: p[3] ?? 1,
  }
}

function resolveMeshUrl(meshFilename: string, urdfUrl: string): string {
  const clean = meshFilename.replace(/^package:\/\//, '').replace(/^\.\//, '')
  const urdfBase = urdfUrl.substring(0, urdfUrl.lastIndexOf('/') + 1)
  return new URL(clean, new URL(urdfBase, window.location.href)).toString()
}

export async function loadURDF(urdfUrl: string, options: LoadURDFOptions = {}): Promise<LoadedURDF> {
  const eagerDisplay = options.eagerDisplay !== false
  const meshConcurrency = options.meshConcurrency ?? DEFAULT_MESH_CONCURRENCY
  const onMeshProgress = options.onMeshProgress
  const onMeshFailed = options.onMeshFailed

  const urdfText = await fetchUrdfText(urdfUrl)

  const doc = new DOMParser().parseFromString(urdfText, 'text/xml')
  const robotEl = doc.querySelector('robot')
  if (!robotEl) throw new Error('Invalid URDF: no <robot>')

  const linkElems = robotEl.querySelectorAll(':scope > link')
  const linkGroups: Record<string, THREE.Group> = {}
  const meshTasks: Array<() => Promise<void>> = []

  linkElems.forEach((linkEl) => {
    const name = linkEl.getAttribute('name') ?? ''
    const group = new THREE.Group()
    group.name = `link_${name}`
    linkGroups[name] = group

    linkEl.querySelectorAll(':scope > visual').forEach((vis) => {
      const visualGroup = new THREE.Group()
      const origin = vis.querySelector(':scope > origin')
      if (origin) {
        const xyz = parseVec3(origin.getAttribute('xyz'))
        const rpy = parseVec3(origin.getAttribute('rpy'))
        visualGroup.position.copy(xyz)
        visualGroup.rotation.set(rpy.x, rpy.y, rpy.z, 'ZYX')
      }

      let matColor = { color: new THREE.Color(0xbbbbbb), opacity: 1 }
      const matEl = vis.querySelector(':scope > material > color')
      if (matEl) matColor = parseColor(matEl.getAttribute('rgba'))

      const material = new THREE.MeshStandardMaterial({
        color: matColor.color,
        metalness: urdfUrl.includes('b601_rs') ? 0.55 : 0.4,
        roughness: urdfUrl.includes('b601_rs') ? 0.38 : 0.5,
        flatShading: false,
        transparent: matColor.opacity < 1,
        opacity: matColor.opacity,
      })

      const geomEl = vis.querySelector(':scope > geometry')
      if (!geomEl) return

      const meshEl = geomEl.querySelector('mesh')
      const boxEl = geomEl.querySelector('box')
      const cylEl = geomEl.querySelector('cylinder')
      const sphEl = geomEl.querySelector('sphere')

      if (meshEl) {
        const filename = meshEl.getAttribute('filename') ?? ''
        const meshUrl = resolveMeshUrl(filename, urdfUrl)
        const meshScale = parseVec3(meshEl.getAttribute('scale'), [1, 1, 1])
        const placeholder = new THREE.Mesh(new THREE.BufferGeometry(), material)
        placeholder.name = `mesh_${name}`
        placeholder.scale.copy(meshScale)
        visualGroup.add(placeholder)
        meshTasks.push(async () => {
          try {
            const geom = await loadSTL(meshUrl)
            placeholder.geometry = geom
          } catch (err) {
            console.warn(`[URDF] STL load failed: ${meshUrl}`, err)
            onMeshFailed?.(meshUrl, err)
            const failMat = new THREE.MeshStandardMaterial({
              color: 0xff3344,
              emissive: 0x550000,
              metalness: 0.2,
              roughness: 0.6,
            })
            placeholder.material = failMat
            placeholder.geometry = new THREE.SphereGeometry(0.008, 8, 8)
          }
        })
      } else if (boxEl) {
        const size = parseVec3(boxEl.getAttribute('size'))
        visualGroup.add(new THREE.Mesh(new THREE.BoxGeometry(size.x, size.y, size.z), material))
      } else if (cylEl) {
        const r = parseFloat(cylEl.getAttribute('radius') ?? '0.01') || 0.01
        const l = parseFloat(cylEl.getAttribute('length') ?? '0.05') || 0.05
        const cyl = new THREE.Mesh(new THREE.CylinderGeometry(r, r, l, 16), material)
        cyl.rotation.x = Math.PI / 2
        visualGroup.add(cyl)
      } else if (sphEl) {
        const r = parseFloat(sphEl.getAttribute('radius') ?? '0.01') || 0.01
        visualGroup.add(new THREE.Mesh(new THREE.SphereGeometry(r, 16, 16), material))
      }

      group.add(visualGroup)
    })
  })

  const jointElems = robotEl.querySelectorAll(':scope > joint')
  const jointMap: Record<string, JointInfo> = {}
  const childLinkSet = new Set<string>()

  jointElems.forEach((jointEl) => {
    const name = jointEl.getAttribute('name') ?? ''
    const type = jointEl.getAttribute('type') ?? 'fixed'
    const parentLink = jointEl.querySelector(':scope > parent')?.getAttribute('link') ?? ''
    const childLink = jointEl.querySelector(':scope > child')?.getAttribute('link') ?? ''
    childLinkSet.add(childLink)

    const origin = jointEl.querySelector(':scope > origin')
    const xyz = parseVec3(origin?.getAttribute('xyz'))
    const rpy = parseVec3(origin?.getAttribute('rpy'))

    const axisEl = jointEl.querySelector(':scope > axis')
    const axis = parseVec3(axisEl?.getAttribute('xyz'), [1, 0, 0]).normalize()

    const limitEl = jointEl.querySelector(':scope > limit')
    const limits = {
      lower: parseFloat(limitEl?.getAttribute('lower') ?? `${-Math.PI}`),
      upper: parseFloat(limitEl?.getAttribute('upper') ?? `${Math.PI}`),
    }

    const jointOrigin = new THREE.Group()
    jointOrigin.name = `joint_origin_${name}`
    jointOrigin.position.copy(xyz)
    jointOrigin.rotation.set(rpy.x, rpy.y, rpy.z, 'ZYX')

    const jointRotator = new THREE.Group()
    jointRotator.name = name
    jointRotator.userData = {
      jointName: name,
      jointType: type,
      axis: axis.clone(),
      limits,
      angle: 0,
    }
    jointOrigin.add(jointRotator)

    const childGroup = linkGroups[childLink]
    if (childGroup) jointRotator.add(childGroup)

    const parentGroup = linkGroups[parentLink]
    if (parentGroup) parentGroup.add(jointOrigin)

    jointMap[name] = { type, parent: parentLink, child: childLink, axis, limits }
  })

  let rootLinkName: string | null = null
  for (const name of Object.keys(linkGroups)) {
    if (!childLinkSet.has(name)) {
      rootLinkName = name
      break
    }
  }

  const robotGroup = new THREE.Group()
  robotGroup.name = robotEl.getAttribute('name') ?? 'robot'
  if (rootLinkName) {
    robotGroup.add(linkGroups[rootLinkName])
  } else {
    console.warn('[URDF] Could not find root link')
  }

  robotGroup.rotation.x = -Math.PI / 2

  const totalMeshes = meshTasks.length
  let loadedMeshes = 0
  const reportProgress = () => {
    loadedMeshes += 1
    onMeshProgress?.(loadedMeshes, totalMeshes)
  }

  const meshesReady = (async () => {
    if (totalMeshes === 0) {
      onMeshProgress?.(0, 0)
      return
    }
    await runPool(
      meshTasks.map((task) => async () => {
        await task()
        reportProgress()
      }),
      meshConcurrency,
    )
  })()

  if (!eagerDisplay) {
    await meshesReady
  }

  return { robot: robotGroup, jointMap, meshesReady }
}

export function updateRobotJoints(
  robot: THREE.Object3D | null,
  jointState: Record<string, number>,
): void {
  if (!robot || !jointState) return
  for (const [jointName, rawAngle] of Object.entries(jointState)) {
    const jointObj = robot.getObjectByName(jointName)
    if (!jointObj || !jointObj.userData?.axis) continue
    const { axis, limits, jointType } = jointObj.userData as {
      axis: THREE.Vector3
      limits: { lower: number; upper: number }
      jointType: string
    }
    if (jointType === 'fixed') continue
    let angle = rawAngle
    if (limits) angle = Math.max(limits.lower, Math.min(limits.upper, angle))
    jointObj.quaternion.setFromAxisAngle(axis, angle)
    jointObj.userData.angle = angle
  }
}

/**
 * Hide every visual mesh inside a URDF link group, WITHOUT hiding the link
 * group itself. This is important: hiding the link group would also hide its
 * child joints/links (because `visible` is inherited in three.js), which would
 * unparent downstream kinematic chains. By only hiding the direct visual
 * sub-groups (and their meshes), we keep the link's transform in the scene
 * graph while making its geometry invisible.
 *
 * Used for closed-loop mechanisms like Reachy Mini's Stewart platform, where
 * URDF's tree-only constraint forces 5 of the 6 rods to dangle from their
 * motor horns at default rotation, looking "broken" / disconnected from the
 * head. Hiding those rods removes the broken look while keeping the head's
 * pose driven by the one rod that's actually in the kinematic chain.
 */
export function hideLinkVisuals(robot: THREE.Object3D | null, linkName: string): void {
  if (!robot) return
  const linkGroup = robot.getObjectByName(`link_${linkName}`)
  if (!linkGroup) return
  linkGroup.children.forEach((child) => {
    // Joint-origin groups (`joint_origin_<name>`) are part of the kinematic
    // chain — we must NOT hide them, otherwise downstream links vanish too.
    if (child.name.startsWith('joint_origin_')) return
    child.visible = false
  })
}

export function hideLinkVisualsMany(
  robot: THREE.Object3D | null,
  linkNames: string[],
): void {
  for (const name of linkNames) hideLinkVisuals(robot, name)
}
