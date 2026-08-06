/**
 * URDF Loader for Three.js (SO101 / dora-bambot)
 *
 * 解析 URDF XML，下载其中引用的 STL mesh，按关节层级构建 Three.js 场景。
 * 关节名与 URDF 保持一致 ("1" ~ "6")，updateRobotJoints 会按 URDF axis 旋转。
 *
 * URDF 坐标系: Z-up, 米为单位
 * 通过在最外层 robotGroup 上绕 X 轴旋转 -90°，适配 Three.js 的 Y-up 约定
 */

import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const stlLoader = new STLLoader();
const stlCache = new Map(); // url -> BufferGeometry

/**
 * 缓存 STL 加载，避免同一个 mesh 被重复请求
 */
function loadSTL(url) {
    if (stlCache.has(url)) {
        return Promise.resolve(stlCache.get(url));
    }
    return new Promise((resolve, reject) => {
        stlLoader.load(
            url,
            (geom) => {
                geom.computeVertexNormals();
                stlCache.set(url, geom);
                resolve(geom);
            },
            undefined,
            (err) => reject(err),
        );
    });
}

function parseVec3(str, fallback = [0, 0, 0]) {
    if (!str) return new THREE.Vector3(...fallback);
    const parts = str.trim().split(/\s+/).map(parseFloat);
    return new THREE.Vector3(
        parts[0] ?? fallback[0],
        parts[1] ?? fallback[1],
        parts[2] ?? fallback[2],
    );
}

function parseColor(rgbaStr) {
    if (!rgbaStr) return { color: 0xcccccc, opacity: 1 };
    const p = rgbaStr.trim().split(/\s+/).map(parseFloat);
    return {
        color: new THREE.Color(p[0] ?? 1, p[1] ?? 1, p[2] ?? 1),
        opacity: p[3] ?? 1,
    };
}

/**
 * 把 URDF mesh filename (相对路径) 解析为可 fetch 的绝对 URL
 * URDF 在 /api/urdf/so101.urdf  →  assets/xxx.stl 映射到 /api/urdf/assets/xxx.stl
 */
function resolveMeshUrl(meshFilename, urdfUrl) {
    const clean = meshFilename.replace(/^package:\/\//, '').replace(/^\.\//, '');
    const urdfBase = urdfUrl.substring(0, urdfUrl.lastIndexOf('/') + 1);
    return new URL(clean, new URL(urdfBase, window.location.href)).toString();
}

/**
 * 加载 URDF 并生成 Three.js 机器人
 * @param {string} urdfUrl
 * @returns {{ robot: THREE.Group, jointMap: Object }}
 */
export async function loadURDF(urdfUrl) {
    const resp = await fetch(urdfUrl);
    if (!resp.ok) throw new Error(`Failed to fetch URDF: ${resp.status}`);
    const urdfText = await resp.text();

    const doc = new DOMParser().parseFromString(urdfText, 'text/xml');
    const robotEl = doc.querySelector('robot');
    if (!robotEl) throw new Error('Invalid URDF: no <robot>');

    // ---------- 收集所有 link ----------
    const linkElems = robotEl.querySelectorAll(':scope > link');
    const linkGroups = {}; // linkName -> THREE.Group (包含 visual mesh)
    const meshJobs = [];

    linkElems.forEach((linkEl) => {
        const name = linkEl.getAttribute('name');
        const group = new THREE.Group();
        group.name = `link_${name}`;
        linkGroups[name] = group;

        // 遍历 <visual>
        const visuals = linkEl.querySelectorAll(':scope > visual');
        visuals.forEach((vis) => {
            const visualGroup = new THREE.Group();

            const origin = vis.querySelector(':scope > origin');
            if (origin) {
                const xyz = parseVec3(origin.getAttribute('xyz'));
                const rpy = parseVec3(origin.getAttribute('rpy'));
                visualGroup.position.copy(xyz);
                visualGroup.rotation.set(rpy.x, rpy.y, rpy.z, 'ZYX'); // URDF 使用 roll-pitch-yaw
            }

            // 解析材质颜色
            let matColor = { color: 0xbbbbbb, opacity: 1 };
            const matEl = vis.querySelector(':scope > material > color');
            if (matEl) matColor = parseColor(matEl.getAttribute('rgba'));

            const material = new THREE.MeshStandardMaterial({
                color: matColor.color,
                metalness: 0.4,
                roughness: 0.5,
                transparent: matColor.opacity < 1,
                opacity: matColor.opacity,
            });

            // 解析 geometry
            const geomEl = vis.querySelector(':scope > geometry');
            if (!geomEl) return;

            const meshEl = geomEl.querySelector('mesh');
            const boxEl = geomEl.querySelector('box');
            const cylEl = geomEl.querySelector('cylinder');
            const sphEl = geomEl.querySelector('sphere');

            if (meshEl) {
                const filename = meshEl.getAttribute('filename');
                const meshUrl = resolveMeshUrl(filename, urdfUrl);
                // 占位 mesh，STL 加载完成后替换 geometry
                const placeholder = new THREE.Mesh(new THREE.BufferGeometry(), material);
                placeholder.name = `mesh_${name}`;
                visualGroup.add(placeholder);

                meshJobs.push(
                    loadSTL(meshUrl)
                        .then((geom) => {
                            placeholder.geometry = geom;
                        })
                        .catch((err) => {
                            console.warn(`[URDF] STL load failed: ${meshUrl}`, err);
                            // 加载失败时用小立方体占位，便于调试
                            placeholder.geometry = new THREE.BoxGeometry(0.02, 0.02, 0.02);
                        }),
                );
            } else if (boxEl) {
                const size = parseVec3(boxEl.getAttribute('size'));
                visualGroup.add(new THREE.Mesh(
                    new THREE.BoxGeometry(size.x, size.y, size.z), material,
                ));
            } else if (cylEl) {
                const r = parseFloat(cylEl.getAttribute('radius')) || 0.01;
                const l = parseFloat(cylEl.getAttribute('length')) || 0.05;
                const cyl = new THREE.Mesh(new THREE.CylinderGeometry(r, r, l, 16), material);
                cyl.rotation.x = Math.PI / 2; // URDF 圆柱默认沿 Z 轴
                visualGroup.add(cyl);
            } else if (sphEl) {
                const r = parseFloat(sphEl.getAttribute('radius')) || 0.01;
                visualGroup.add(new THREE.Mesh(new THREE.SphereGeometry(r, 16, 16), material));
            }

            group.add(visualGroup);
        });
    });

    // ---------- 构建关节层级 ----------
    const jointElems = robotEl.querySelectorAll(':scope > joint');
    const jointMap = {};
    const childLinkSet = new Set();

    jointElems.forEach((jointEl) => {
        const name = jointEl.getAttribute('name');
        const type = jointEl.getAttribute('type');
        const parentLink = jointEl.querySelector(':scope > parent').getAttribute('link');
        const childLink = jointEl.querySelector(':scope > child').getAttribute('link');
        childLinkSet.add(childLink);

        const origin = jointEl.querySelector(':scope > origin');
        const xyz = parseVec3(origin?.getAttribute('xyz'));
        const rpy = parseVec3(origin?.getAttribute('rpy'));

        const axisEl = jointEl.querySelector(':scope > axis');
        const axis = parseVec3(axisEl?.getAttribute('xyz'), [1, 0, 0]).normalize();

        const limitEl = jointEl.querySelector(':scope > limit');
        const limits = {
            lower: parseFloat(limitEl?.getAttribute('lower') ?? -Math.PI),
            upper: parseFloat(limitEl?.getAttribute('upper') ?? Math.PI),
        };

        // 构造两层: 外层承载静态 origin 变换，内层用于绕 axis 施加关节角
        const jointOrigin = new THREE.Group();
        jointOrigin.name = `joint_origin_${name}`;
        jointOrigin.position.copy(xyz);
        jointOrigin.rotation.set(rpy.x, rpy.y, rpy.z, 'ZYX');

        const jointRotator = new THREE.Group();
        jointRotator.name = name; // 关节名直接作为 object name，便于 getObjectByName
        jointRotator.userData = {
            jointName: name,
            jointType: type,
            axis: axis.clone(),
            limits,
            angle: 0,
        };

        jointOrigin.add(jointRotator);

        const childGroup = linkGroups[childLink];
        if (childGroup) jointRotator.add(childGroup);

        const parentGroup = linkGroups[parentLink];
        if (parentGroup) parentGroup.add(jointOrigin);

        jointMap[name] = { type, parent: parentLink, child: childLink, axis, limits };
    });

    // ---------- 找到根 link ----------
    let rootLinkName = null;
    for (const name of Object.keys(linkGroups)) {
        if (!childLinkSet.has(name)) {
            rootLinkName = name;
            break;
        }
    }

    const robotGroup = new THREE.Group();
    robotGroup.name = robotEl.getAttribute('name') || 'robot';
    if (rootLinkName) {
        robotGroup.add(linkGroups[rootLinkName]);
    } else {
        console.warn('[URDF] Could not find root link');
    }

    // URDF 是 Z-up, Three.js 默认 Y-up - 绕 X 轴旋转 -90°
    robotGroup.rotation.x = -Math.PI / 2;

    // 等所有 STL 加载完再返回
    await Promise.all(meshJobs);

    return { robot: robotGroup, jointMap };
}

/**
 * 根据 jointState (关节名 -> 弧度) 更新机器人姿态
 * @param {THREE.Group} robot
 * @param {Object<string, number>} jointState
 */
export function updateRobotJoints(robot, jointState) {
    if (!robot || !jointState) return;

    for (const [jointName, rawAngle] of Object.entries(jointState)) {
        const jointObj = robot.getObjectByName(jointName);
        if (!jointObj || !jointObj.userData || !jointObj.userData.axis) continue;

        const { axis, limits, jointType } = jointObj.userData;
        if (jointType === 'fixed') continue;

        let angle = rawAngle;
        if (limits) {
            angle = Math.max(limits.lower, Math.min(limits.upper, angle));
        }

        // 沿 URDF axis 施加旋转
        jointObj.quaternion.setFromAxisAngle(axis, angle);
        jointObj.userData.angle = angle;
    }
}
