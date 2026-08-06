/**
 * BotverseX 前端应用
 * WebSocket 实时关节数据 + Three.js 3D 可视化
 */

// 配置
const WS_URL = `ws://${window.location.host}/ws/ui`;
const RECORD_API = '/api/record';

// 全局状态
let ws = null;
let isRecording = false;
let frameCount = 0;
let lastFrameTime = 0;
let fps = 0;
let fpsFrames = 0;
let fpsLastTime = 0;
// 手动连接模式: 只有用户点击按钮触发的断开才会禁用自动重连
let userRequestedDisconnect = true; // 初始默认不连 (等用户点"连接")

// Three.js 相关
let THREE = null;
let scene, camera, renderer, controls;
let armGroup = null;
let robot = null;
let urdfLoaded = false;
let isThreeReady = false;
// URDF loader 引用 (一次 import，避免每帧重复解析)
let urdfModule = null;

// DOM 元素
const elements = {
    wsStatus: document.getElementById('ws-status'),
    btnConnect: document.getElementById('btn-connect'),
    btnRecord: document.getElementById('btn-record'),
    recordStatus: document.getElementById('record-status'),
    recordInfo: document.getElementById('record-info'),
    fpsValue: document.getElementById('fps-value'),
    frameCount: document.getElementById('frame-count'),
    lastUpdate: document.getElementById('last-update'),
    viewerFps: document.getElementById('viewer-fps'),
};

// 关节配置
const JOINT_CONFIG = {
    "1": { min: -2.6, max: 2.6, label: '关节 1' },
    "2": { min: -1.7, max: 1.7, label: '关节 2' },
    "3": { min: -1.7, max: 1.7, label: '关节 3' },
    "4": { min: -1.5, max: 1.5, label: '关节 4' },
    "5": { min: -2.6, max: 2.6, label: '关节 5' },
    "6": { min: -0.5, max: 0.5, label: '关节 6' },
};

// ============== Three.js 3D 渲染 ==============

async function initThree() {
    const canvas = document.getElementById('three-canvas');
    if (!canvas) {
        console.warn('[3D] Canvas not found');
        return;
    }

    // Import Three.js (using import map)
    THREE = await import('three');
    const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    // Camera
    const container = canvas.parentElement;
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera = new THREE.PerspectiveCamera(50, w / h, 0.01, 100);
    camera.position.set(0.4, 0.35, 0.5);
    camera.lookAt(0, 0.15, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Controls
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.target.set(0, 0.15, 0);
    controls.update();

    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambient);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1);
    dirLight.position.set(1, 2, 1);
    scene.add(dirLight);

    const backLight = new THREE.DirectionalLight(0x8888ff, 0.3);
    backLight.position.set(-1, 0, -1);
    scene.add(backLight);

    // Ground grid
    const grid = new THREE.GridHelper(1, 20, 0x333333, 0x222222);
    grid.position.y = 0;
    scene.add(grid);

    // Axes helper (X=红 Y=绿 Z=蓝) — 调试用，正式环境可移除
    const axesHelper = new THREE.AxesHelper(0.1);
    scene.add(axesHelper);

    // Load URDF robot
    try {
        urdfModule = await import('./urdf_loader.js');
        const { robot: loadedRobot } = await urdfModule.loadURDF('/api/urdf/so101.urdf');
        robot = loadedRobot;

        // 用 Box3 自动居中 URDF 模型 —— URDF 原始 base link 不在原点
        const bbox = new THREE.Box3().setFromObject(robot);
        const center = bbox.getCenter(new THREE.Vector3());
        const size = bbox.getSize(new THREE.Vector3());
        // 把机器人底部放到 y=0，并让水平方向以原点为中心
        const wrapper = new THREE.Group();
        wrapper.add(robot);
        robot.position.x -= center.x;
        robot.position.z -= center.z;
        robot.position.y -= bbox.min.y;

        // Remove old arm if exists
        if (armGroup) {
            scene.remove(armGroup);
        }
        armGroup = wrapper;
        scene.add(armGroup);

        // 根据模型尺寸调整相机距离
        const maxDim = Math.max(size.x, size.y, size.z);
        const camDist = maxDim * 2.2;
        camera.position.set(camDist * 0.7, camDist * 0.6, camDist * 0.9);
        controls.target.set(0, size.y * 0.5, 0);
        controls.update();

        // Set initial pose
        urdfModule.updateRobotJoints(robot, {
            "1": 0.0,
            "2": 0.0,
            "3": 0.0,
            "4": 0.0,
            "5": 0.0,
            "6": 0.0,
        });
        urdfLoaded = true;
        console.log('[3D] URDF loaded, bbox size:', size, 'center:', center);
    } catch (e) {
        console.warn('[3D] URDF loading failed, using programmatic arm:', e);
        // Fallback to programmatic arm
        createArm({
            "1": -0.09,
            "2": 1.44,
            "3": -2.49,
            "4": -1.13,
            "5": -0.02,
            "6": -0.02
        });
    }

    isThreeReady = true;
    console.log('[3D] Three.js initialized');

    // Animation loop
    let viewerFrameCount = 0;
    let viewerLastTime = performance.now();

    function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);

        // Update viewer FPS
        viewerFrameCount++;
        const now = performance.now();
        if (now - viewerLastTime >= 1000) {
            const vfps = viewerFrameCount;
            viewerFrameCount = 0;
            viewerLastTime = now;
            if (elements.viewerFps) {
                elements.viewerFps.textContent = `${vfps} FPS`;
            }
        }
    }
    animate();

    // Resize handler
    window.addEventListener('resize', () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    });
}

function createArm(angles) {
    if (!scene) return;

    // Remove old arm
    if (armGroup) {
        scene.remove(armGroup);
    }

    armGroup = new THREE.Group();

    // Materials
    const gold = new THREE.MeshStandardMaterial({
        color: 0xD4A017,
        metalness: 0.5,
        roughness: 0.3
    });
    const gray = new THREE.MeshStandardMaterial({
        color: 0x666666,
        metalness: 0.7,
        roughness: 0.3
    });
    const darkGray = new THREE.MeshStandardMaterial({
        color: 0x444444,
        metalness: 0.6,
        roughness: 0.4
    });

    // Base
    const base = new THREE.Mesh(
        new THREE.CylinderGeometry(0.06, 0.08, 0.04, 16),
        darkGray
    );
    base.position.y = 0.02;
    armGroup.add(base);

    // Joint 1: Shoulder Pan (rotates Y)
    const j1 = new THREE.Group();
    j1.position.y = 0.04;
    j1.rotation.y = angles["1"] || 0;
    armGroup.add(j1);

    // Shoulder housing
    const shoulderHousing = new THREE.Mesh(
        new THREE.CylinderGeometry(0.05, 0.05, 0.06, 16),
        gray
    );
    shoulderHousing.position.y = 0.03;
    j1.add(shoulderHousing);

    // Joint 2: Shoulder Lift (child of j1, so it rotates with shoulder_pan)
    const j2 = new THREE.Group();
    j2.position.y = 0.06;
    j1.add(j2);

    // Upper arm
    const upperArm = new THREE.Mesh(
        new THREE.BoxGeometry(0.04, 0.22, 0.04),
        gold
    );
    upperArm.position.y = 0.11;
    j2.add(upperArm);

    // Joint 3: Elbow Flex
    const j3 = new THREE.Group();
    j3.position.y = 0.22;
    j2.add(j3);

    // Elbow joint
    const elbowJoint = new THREE.Mesh(
        new THREE.SphereGeometry(0.035, 16, 16),
        gray
    );
    j3.add(elbowJoint);

    // Lower arm
    const lowerArm = new THREE.Mesh(
        new THREE.BoxGeometry(0.035, 0.18, 0.035),
        gold
    );
    lowerArm.position.y = 0.09;
    j3.add(lowerArm);

    // Joint 4: Wrist Flex
    const j4 = new THREE.Group();
    j4.position.y = 0.18;
    j3.add(j4);

    // Wrist joint
    const wristJoint = new THREE.Mesh(
        new THREE.SphereGeometry(0.028, 16, 16),
        gray
    );
    j4.add(wristJoint);

    // Hand
    const hand = new THREE.Mesh(
        new THREE.BoxGeometry(0.05, 0.06, 0.035),
        gold
    );
    hand.position.y = 0.05;
    j4.add(hand);

    // Joint 5: Wrist Roll
    const j5 = new THREE.Group();
    j5.position.y = 0.08;
    j4.add(j5);

    // Joint 6: Gripper
    const gripperBase = new THREE.Mesh(
        new THREE.BoxGeometry(0.04, 0.04, 0.03),
        darkGray
    );
    gripperBase.position.y = 0.04;
    j5.add(gripperBase);

    // Gripper fingers
    const fingerOffset = (angles["6"] || 0) * 0.015;
    const fingerGeom = new THREE.BoxGeometry(0.012, 0.04, 0.02);

    const leftFinger = new THREE.Mesh(fingerGeom, gold);
    leftFinger.position.set(-0.015 - fingerOffset, 0.08, 0);
    j5.add(leftFinger);

    const rightFinger = new THREE.Mesh(fingerGeom, gold);
    rightFinger.position.set(0.015 + fingerOffset, 0.08, 0);
    j5.add(rightFinger);

    // Apply rotations
    j2.rotation.x = angles["2"] || 0;
    j3.rotation.x = angles["3"] || 0;
    j4.rotation.x = angles["4"] || 0;
    j5.rotation.z = angles["5"] || 0;

    scene.add(armGroup);
}

// ============== WebSocket ==============

function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        console.log('[WS] Already connecting/connected, skip');
        return;
    }

    userRequestedDisconnect = false;
    updateStatus('connecting');
    console.log(`[WS] Connecting to ${WS_URL}...`);

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('[WS] Connected');
        updateStatus('connected');
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'joint_update') {
                updateJoints(data.joints);
                updateFPS();
                // Update 3D arm (URDF 已加载时用真实模型，否则用 fallback 的 programmatic arm)
                if (isThreeReady && data.joints) {
                    if (urdfLoaded && robot && urdfModule) {
                        urdfModule.updateRobotJoints(robot, data.joints);
                    } else {
                        createArm(data.joints);
                    }
                }
            }
        } catch (e) {
            console.error('[WS] Parse error:', e);
        }
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected');
        updateStatus('disconnected');
        // 只有非用户主动断开时，才做一次温和的自动重连 (网络抖动恢复)
        if (!userRequestedDisconnect) {
            console.log('[WS] Attempting auto-reconnect in 3s...');
            setTimeout(() => {
                if (!userRequestedDisconnect) connect();
            }, 3000);
        }
    };

    ws.onerror = (error) => {
        console.error('[WS] Error:', error);
    };
}

function disconnect() {
    userRequestedDisconnect = true;
    if (ws) {
        console.log('[WS] User requested disconnect');
        try { ws.close(1000, 'user disconnect'); } catch (_) {}
    }
    updateStatus('disconnected');
}

function toggleConnection() {
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        connect();
    } else {
        disconnect();
    }
}

function updateStatus(status) {
    elements.wsStatus.className = 'status ' + status;
    const textEl = elements.wsStatus.querySelector('.status-text');
    if (textEl) {
        textEl.textContent = {
            'connected': '已连接',
            'disconnected': '未连接',
            'connecting': '连接中...'
        }[status] || status;
    }

    // 同步按钮 (label + class + disabled)
    const btn = elements.btnConnect;
    if (!btn) return;
    const labelEl = btn.querySelector('.btn-label');
    btn.classList.remove('is-connected', 'is-connecting');
    btn.disabled = false;

    if (status === 'connected') {
        btn.classList.add('is-connected');
        if (labelEl) labelEl.textContent = '断开';
        btn.title = '断开 WebSocket';
    } else if (status === 'connecting') {
        btn.classList.add('is-connecting');
        btn.disabled = true;
        if (labelEl) labelEl.textContent = '连接中';
        btn.title = '正在连接...';
    } else {
        if (labelEl) labelEl.textContent = '连接';
        btn.title = '连接到后端 WebSocket';
    }
}

// ============== 关节数据更新 ==============

function updateJoints(joints) {
    const now = new Date();
    elements.lastUpdate.textContent = now.toLocaleTimeString();

    for (const [name, value] of Object.entries(joints)) {
        const valueEl = document.getElementById(`joint-${name}`);
        const barEl = document.getElementById(`bar-${name}`);

        if (valueEl && barEl) {
            valueEl.textContent = value.toFixed(2);

            const config = JOINT_CONFIG[name];
            if (config) {
                const range = config.max - config.min;
                const percent = ((value - config.min) / range) * 100;
                barEl.style.width = `${Math.max(0, Math.min(100, percent))}%`;
            }
        }
    }

    frameCount++;
    lastFrameTime = now.getTime();
    elements.frameCount.textContent = frameCount;
}

function updateFPS() {
    fpsFrames++;
    const now = performance.now();

    if (now - fpsLastTime >= 1000) {
        fps = Math.round(fpsFrames * 1000 / (now - fpsLastTime));
        fpsFrames = 0;
        fpsLastTime = now;
        elements.fpsValue.textContent = fps;
    }
}

// ============== 录制控制 ==============

async function toggleRecording() {
    if (isRecording) {
        await stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        const response = await fetch(RECORD_API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'start' })
        });

        const result = await response.json();

        if (result.success) {
            isRecording = true;
            frameCount = 0;
            elements.btnRecord.classList.add('recording');
            elements.btnRecord.innerHTML = '<span class="btn-icon">⏹</span>停止录制';
            elements.recordStatus.textContent = '录制中...';
            elements.recordStatus.classList.add('active');
            elements.recordInfo.textContent = '';
            console.log('[REC] Recording started');
        }
    } catch (e) {
        console.error('[REC] Start error:', e);
    }
}

async function stopRecording() {
    try {
        const response = await fetch(RECORD_API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'stop' })
        });

        const result = await response.json();

        if (result.success) {
            isRecording = false;
            elements.btnRecord.classList.remove('recording');
            elements.btnRecord.innerHTML = '<span class="btn-icon">⏺</span>开始录制';
            elements.recordStatus.textContent = '已停止';
            elements.recordStatus.classList.remove('active');

            if (result.frames > 0) {
                elements.recordInfo.textContent = `已保存 ${result.frames} 帧到 ${result.filename}`;
            } else {
                elements.recordInfo.textContent = '无数据录制';
            }

            console.log('[REC] Recording stopped:', result);
        }
    } catch (e) {
        console.error('[REC] Stop error:', e);
    }
}

// ============== 初始化 ==============

function init() {
    // 绑定录制按钮
    elements.btnRecord.addEventListener('click', toggleRecording);

    // 绑定连接按钮 (手动连接模式)
    if (elements.btnConnect) {
        elements.btnConnect.addEventListener('click', toggleConnection);
    }

    // 初始化按钮/指示灯为未连接状态
    updateStatus('disconnected');

    // 启动 Three.js
    initThree();

    // 注意: 页面加载时不自动连接 WebSocket, 由用户点击右上角"连接"按钮触发
    console.log('[APP] BotverseX UI initialized (手动连接模式, 请点击右上角"连接"按钮)');
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);
