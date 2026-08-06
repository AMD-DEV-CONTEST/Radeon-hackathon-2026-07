/* 废土酒吧 3D 场景：真实几何环境 + 脚本化角色演出 */
const params = new URLSearchParams(location.search);
const batch = params.get("batch") || "";

const titleEl = document.getElementById("scene-title");
const assetsEl = document.getElementById("scene-assets");
const listEl = document.getElementById("asset-list");
const statusEl = document.getElementById("scene-status");
const actionEl = document.getElementById("scene-action");
const soundBtn = document.getElementById("sound-btn");
const overlay = document.getElementById("start-overlay");
document.getElementById("ov-title").textContent = batch ? `「${batch}」3D 场景` : "3D 场景";

let scene, camera, renderer, controls;
let music, ambient, clink, clinkTimer, soundOn = false;

let charGroup = null, rigRoot = null, charKind = "none";
let proc = null, glbMixer = null, glass = null;
let shadow = null, charPos = null, charTarget = null, charFacing = 1;
let walkResolve = null;
let dustPts = null;
let webglOK = true;
let lastT = performance.now();
let state = "idle";
let drinkT = 0, toastT = 0, rag = null;
const CHAR_H = 1.9;
const BASE_YAW = 0.08;

window.addEventListener("error", (e) => {
  statusEl.textContent = "脚本错误: " + (e.message || e.type);
  overlay.classList.add("hidden");
});

try {
  init();
  loadConfig();
} catch (err) {
  statusEl.textContent = "3D 初始化失败: " + err.message + "（浏览器是否支持 WebGL？可尝试 Chrome/Edge）";
  overlay.classList.add("hidden");
}

async function loadConfig() {
  statusEl.textContent = "加载场景配置…";
  try {
    const resp = await fetch(`/api/scene?batch=${encodeURIComponent(batch)}`);
    if (!resp.ok) throw new Error((await resp.text()).slice(0, 200));
    const cfg = await resp.json();
    titleEl.textContent = cfg.batch;
    await buildScene(cfg.assets);
    statusEl.textContent = "就绪 · 自动演出 · 拖拽旋转 · 滚轮缩放";
  } catch (err) {
    statusEl.textContent = "加载失败: " + err.message;
  }
}

function init() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d0a);
  scene.fog = new THREE.FogExp2(0x0b0d0a, 0.05);
  camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 100);
  camera.position.set(0, 1.9, 5.2);
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (err) {
    webglOK = false;
    return;
  }
  if (!renderer.getContext()) {
    webglOK = false;
    return;
  }
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;
  document.getElementById("canvas-wrap").appendChild(renderer.domElement);
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 1.2, -0.8);
  controls.maxPolarAngle = 1.48;
  controls.minDistance = 2.5;
  controls.maxDistance = 12;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.6;
  controls.addEventListener("start", () => { controls.autoRotate = false; });
  addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });
  animate();
}

function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min((now - lastT) / 1000, 0.1);
  lastT = now;
  controls.update();
  if (dustPts) {
    const pos = dustPts.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      let y = pos.getY(i) + dt * 0.06;
      if (y > 2.8) y = 0.1;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
  }
  if (charGroup) updateCharacter(dt, now);
  renderer.render(scene, camera);
}

/* ---------------- 角色更新：走位 / 3D 旋转 / 喝酒动作 ---------------- */
function updateCharacter(dt, now) {
  if (state === "walk" && charTarget) {
    const dx = charTarget.x - charPos.x, dz = charTarget.z - charPos.z;
    const dist = Math.hypot(dx, dz);
    const speed = 1.4 * dt;
    if (dist <= speed) {
      charPos.set(charTarget.x, 0, charTarget.z);
      charTarget = null;
      state = "stand";
      if (walkResolve) { const r = walkResolve; walkResolve = null; r(); }
    } else {
      charPos.x += dx / dist * speed;
      charPos.z += dz / dist * speed;
      charFacing = dx >= 0 ? 1 : -1;
    }
  }
  const walkPhase = now * 0.011;
  const moving = state === "walk";
  const breathing = Math.sin(now * 0.0022);
  const bob = moving ? Math.abs(Math.sin(walkPhase)) * 0.05 : Math.abs(breathing) * 0.012;
  const stretch = moving ? Math.sin(walkPhase * 2) : breathing;
  const sy = 1 + stretch * (moving ? 0.05 : 0.008);
  const sx = 1 - stretch * (moving ? 0.04 : 0.006);

  charGroup.position.set(charPos.x, bob, charPos.z);
  rigRoot.rotation.y = BASE_YAW + breathing * 0.02;
  rigRoot.rotation.z = moving ? -charFacing * Math.sin(walkPhase) * 0.03 : 0;
  rigRoot.scale.x = charFacing * sx;
  rigRoot.scale.y = sy;

  if (charKind === "proc" && proc) {
    const sw = Math.sin(walkPhase);
    let armRX = -sw * (moving ? 0.55 : 0.05);
    let armRZ = 0;
    let glassVisible = false;
    if (state === "drink") {
      armRX = -smoothstep(drinkT) * 1.35;
      armRZ = 0.12;
      glassVisible = true;
    } else if (state === "toast") {
      armRX = -0.3;
      armRZ = -0.9 * smoothstep(toastT);
      glassVisible = true;
    } else if (state === "wipe") {
      armRX = -0.55;
      armRZ = Math.sin(now * 0.004) * 0.7;
    }
    proc.armR.rotation.x = armRX;
    proc.armR.rotation.z = armRZ;
    proc.armL.rotation.x = sw * (moving ? 0.55 : 0.05);
    proc.legL.rotation.x = -sw * (moving ? 0.48 : 0);
    proc.legR.rotation.x = sw * (moving ? 0.48 : 0);
    if (glass) {
      glass.visible = glassVisible;
      glass.rotation.x = state === "drink" ? -0.45 : 0;
      glass.rotation.z = state === "drink" ? 0.15 : 0;
    }
    if (rag) rag.visible = state === "wipe";
  } else if (charKind === "glb") {
    if (glass) glass.visible = false;
    if (glbMixer) glbMixer.update(dt);
  }
  if (shadow) shadow.position.set(charPos.x, 0.02, charPos.z);
}

function smoothstep(t) {
  t = Math.max(0, Math.min(1, t));
  return t * t * (3 - 2 * t);
}

/* ---------------- 环境：真实几何 ----------------
   房间 9(x) × 7(z)，后墙 z=-3.5，吧台靠右，两张桌在左侧 */
function buildRoom(a) {
  const loader = new THREE.TextureLoader();
  const std = (opt) => new THREE.MeshStandardMaterial(opt);
  const wood = std({ color: 0x4a3a26, roughness: 0.85, metalness: 0.05 });
  const metal = std({ color: 0x5c5a52, roughness: 0.55, metalness: 0.65 });
  const dark = std({ color: 0x2b2a24, roughness: 0.9, metalness: 0.1 });
  const neonMat = (c, e) => std({ color: c, emissive: e, emissiveIntensity: 1.4, roughness: 0.4 });

  // 地面
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9, 7), wood);
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);

  // 后墙 + 两侧墙
  const backWall = new THREE.Mesh(new THREE.BoxGeometry(9, 3.6, 0.2), dark);
  backWall.position.set(0, 1.8, -3.5);
  scene.add(backWall);
  for (const sx of [-1, 1]) {
    const wall = new THREE.Mesh(new THREE.BoxGeometry(0.2, 3.6, 7), dark);
    wall.position.set(sx * 4.5, 1.8, 0);
    scene.add(wall);
  }

  // 概念图作为后墙大幅海报（带深度置换与法线）
  if (a.concept) {
    // 环境照片 → 3D：用 W2 深度图把整幅照片置换出真实几何（酒架/吧台随镜头有视差）
    const poster = new THREE.Mesh(
      new THREE.PlaneGeometry(8.6, 3.3, 128, 64),
      new THREE.MeshStandardMaterial({
        map: tex(loader, a.concept),
        displacementMap: tex(loader, a.depth),
        displacementScale: a.depth ? -0.5 : 0,
        normalMap: tex(loader, a.materials && a.materials.normal),
        roughness: 0.85,
        metalness: 0.12,
      })
    );
    poster.position.set(0, 1.9, -3.39);
    scene.add(poster);
    listEl.appendChild(item("背景海报", a.concept.filename));
  }

  // 吧台（右侧）：台面 + 前面板
  const counterTop = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.14, 4.8), wood);
  counterTop.position.set(3.6, 1.12, 0);
  scene.add(counterTop);
  const counterFront = new THREE.Mesh(new THREE.BoxGeometry(1.7, 1.1, 4.8), metal);
  counterFront.position.set(3.6, 0.55, 0);
  scene.add(counterFront);

  // 后墙酒架 + 酒瓶
  const shelfMat = wood;
  for (const sy of [2.15, 2.6]) {
    const shelf = new THREE.Mesh(new THREE.BoxGeometry(4.6, 0.07, 0.4), shelfMat);
    shelf.position.set(-1.2, sy, -3.28);
    scene.add(shelf);
    const bottleColors = [0x3f6f5a, 0x7a4a2f, 0x4f5f8f, 0x8f3f3f, 0x5f8f4f, 0x8f7f3f, 0x3f7f8f];
    for (let i = 0; i < 7; i++) {
      const b = new THREE.Mesh(
        new THREE.CylinderGeometry(0.055, 0.06, 0.26, 8),
        std({ color: bottleColors[i % bottleColors.length], roughness: 0.3, metalness: 0.2 })
      );
      b.position.set(-3.1 + i * 0.62, sy + 0.15, -3.28);
      scene.add(b);
    }
  }

  // 桌子 + 凳子（左侧两张）
  for (const [tx, tz] of [[-1.6, -1.5], [-1.6, 0.8]]) {
    const top = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.08, 1.0), wood);
    top.position.set(tx, 0.82, tz);
    scene.add(top);
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.78, 8), metal);
    leg.position.set(tx, 0.39, tz);
    scene.add(leg);
    for (const off of [[0.55, 0], [-0.55, 0]]) {
      const stool = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 0.5, 10), dark);
      stool.position.set(tx + off[0], 0.25, tz);
      scene.add(stool);
    }
  }

  // 霓虹招牌（发光文字）
  const signCanvas = document.createElement("canvas");
  signCanvas.width = 1024; signCanvas.height = 128;
  const sctx = signCanvas.getContext("2d");
  sctx.fillStyle = "#000";
  sctx.fillRect(0, 0, 1024, 128);
  sctx.font = "bold 72px 'Arial Black', sans-serif";
  sctx.textAlign = "center";
  sctx.textBaseline = "middle";
  sctx.shadowColor = "#ff7733";
  sctx.shadowBlur = 24;
  sctx.fillStyle = "#ffaa55";
  sctx.fillText("WASTELAND BAR", 512, 64);
  const signTex = new THREE.CanvasTexture(signCanvas);
  signTex.encoding = THREE.sRGBEncoding;
  const sign = new THREE.Mesh(
    new THREE.PlaneGeometry(4.2, 0.55),
    new THREE.MeshBasicMaterial({ map: signTex, transparent: true })
  );
  sign.position.set(0, 2.95, -3.38);
  scene.add(sign);

  // 吊灯 + 灯光
  for (const lx of [-2.2, 2.0]) {
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 12), neonMat(0xffcc88, 0xffaa55));
    bulb.position.set(lx, 3.05, -1.2);
    scene.add(bulb);
    const pl = new THREE.PointLight(0xffaa55, 1.3, 10);
    pl.position.set(lx, 2.7, -1.2);
    scene.add(pl);
  }
  const neonR = new THREE.PointLight(0xff8844, 1.5, 12);
  neonR.position.set(1.2, 2.6, -2.0);
  scene.add(neonR);

  // 灰尘粒子
  const n = 260;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 7.5;
    pos[i * 3 + 1] = Math.random() * 2.6;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 5.5;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  dustPts = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xccbb99, size: 0.02, transparent: true, opacity: 0.5 }));
  scene.add(dustPts);
}

function tex(loader, u) {
  if (!u) return null;
  const t = loader.load(u.url, undefined, undefined, () => {
    statusEl.textContent = "纹理加载失败: " + u.url;
  });
  t.encoding = THREE.sRGBEncoding;
  return t;
}

/* ---------------- 角色：W7 3D 模型 / 内置低模酒保 ---------------- */
function loadGLB(url) {
  return new Promise((resolve, reject) => {
    new THREE.GLTFLoader().load(url, (gltf) => {
      const root = gltf.scene;
      root.updateWorldMatrix(true, true);
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3());
      const scale = CHAR_H / Math.max(size.y, 1e-6);
      root.scale.setScalar(scale);
      box.setFromObject(root);
      const c = box.getCenter(new THREE.Vector3());
      root.position.x -= c.x;
      root.position.z -= c.z;
      root.position.y -= box.min.y;
      resolve({ root, animations: gltf.animations || [] });
    }, undefined, reject);
  });
}

/* 内置低模酒保：未生成 W7 模型时演示「3D 角色在 3D 酒吧喝酒」 */
function buildProcedural() {
  charKind = "proc";
  const mat = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, metalness: 0.04 });
  const limb = (w, h, d, color, px, py) => {
    const pivot = new THREE.Group();
    pivot.position.set(px, py, 0);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color));
    mesh.position.y = -h / 2;
    pivot.add(mesh);
    rigRoot.add(pivot);
    return pivot;
  };
  proc = {
    legL: limb(0.16, 0.95, 0.18, 0x37312a, -0.11, 0.95),
    legR: limb(0.16, 0.95, 0.18, 0x37312a, 0.11, 0.95),
    armL: limb(0.12, 0.55, 0.13, 0x8d7b60, -0.34, 1.52),
    armR: limb(0.12, 0.55, 0.13, 0x8d7b60, 0.34, 1.52),
  };
  // 靴子（旧皮靴）
  for (const side of [-1, 1]) {
    const shoe = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.08, 0.26), mat(0x241f19));
    shoe.position.set(0, 0.035, 0.04);
    (side < 0 ? proc.legL : proc.legR).add(shoe);
  }
  // 躯干：脏衬衫 + 旧皮马甲
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.58, 0.30), mat(0x8d7b60));
  torso.position.y = 1.34;
  rigRoot.add(torso);
  const vest = new THREE.Mesh(new THREE.BoxGeometry(0.50, 0.36, 0.34), mat(0x6b4526));
  vest.position.y = 1.24;
  rigRoot.add(vest);
  // 皮革腰带 + 金属扣
  const belt = new THREE.Mesh(new THREE.BoxGeometry(0.50, 0.07, 0.34), mat(0x4a3422));
  belt.position.y = 1.05;
  rigRoot.add(belt);
  const buckle = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.09, 0.36), mat(0x8a7a5a));
  buckle.position.set(0, 1.05, 0.02);
  rigRoot.add(buckle);
  // 围裙（油渍深色）
  const apron = new THREE.Mesh(new THREE.BoxGeometry(0.40, 0.38, 0.10), mat(0x5c4630));
  apron.position.set(0, 1.06, 0.16);
  rigRoot.add(apron);
  // 头巾（褪色红）
  const bandana = new THREE.Mesh(new THREE.BoxGeometry(0.20, 0.09, 0.22), mat(0x7a2f2a));
  bandana.position.set(0, 1.64, 0.02);
  rigRoot.add(bandana);
  // 头（风霜肤色）+ 短发
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 14), mat(0xb08a62));
  head.position.y = 1.80;
  rigRoot.add(head);
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 14), mat(0x2a241d));
  hair.position.set(0, 1.87, -0.02);
  hair.scale.set(1.02, 0.7, 1.02);
  rigRoot.add(hair);
  // 额头护目镜（废土标配）
  const strap = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.03, 0.05), mat(0x2c2a26));
  strap.position.set(0, 1.88, 0.02);
  rigRoot.add(strap);
  for (const side of [-1, 1]) {
    const gog = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.06, 10), mat(0x55524a));
    gog.rotation.x = Math.PI / 2;
    gog.position.set(side * 0.075, 1.87, 0.035);
    rigRoot.add(gog);
  }
  // 手 + 酒杯（握在右手）+ 擦吧台抹布
  for (const a of [proc.armL, proc.armR]) {
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.06, 10, 8), mat(0xb08a62));
    hand.position.y = -0.32;
    a.add(hand);
  }
  glass = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045, 0.05, 0.14, 12),
    new THREE.MeshStandardMaterial({ color: 0xbfe8e0, transparent: true, opacity: 0.55, roughness: 0.1, metalness: 0.1 })
  );
  glass.position.set(0.02, -0.36, 0.02);
  glass.visible = false;
  proc.armR.add(glass);
  rag = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.06, 0.05), mat(0x9a927c));
  rag.position.set(0.02, -0.36, 0.03);
  rag.visible = false;
  proc.armR.add(rag);

  // 吧台和桌上的常驻酒杯
  const glassMat = new THREE.MeshStandardMaterial({ color: 0xbfe8e0, transparent: true, opacity: 0.5, roughness: 0.12, metalness: 0.1 });
  const barGlass = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.14, 12), glassMat);
  barGlass.position.set(3.5, 1.26, 0.3);
  scene.add(barGlass);
  const tableGlass = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.14, 12), glassMat);
  tableGlass.position.set(-1.6, 0.93, -1.5);
  scene.add(tableGlass);
}

async function buildCharacter(a) {
  charGroup = new THREE.Group();
  rigRoot = new THREE.Group();
  charGroup.add(rigRoot);
  scene.add(charGroup);
  charPos = new THREE.Vector3(3.6, 0, 0.4);

  if (a.model) {
    statusEl.textContent = "加载 3D 模型…";
    try {
      const res = await loadGLB(a.model.url);
      rigRoot.add(res.root);
      if (res.animations.length) {
        glbMixer = new THREE.AnimationMixer(res.root);
        glbMixer.clipAction(res.animations[0]).play();
      }
      charKind = "glb";
      listEl.appendChild(item("3D 角色模型（W7 · TripoSR）", a.model.filename));
    } catch (err) {
      statusEl.textContent = "3D 模型加载失败，使用内置酒保: " + err.message;
      buildProcedural();
    }
  } else {
    buildProcedural();
    listEl.appendChild(item("3D 角色（内置低模酒保）", "procedural"));
  }

  shadow = new THREE.Mesh(
    new THREE.CircleGeometry(0.55, 24),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false })
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(charPos.x, 0.02, charPos.z);
  scene.add(shadow);
}

/* ---------------- 自动演出：3D 角色在 3D 酒吧里喝酒 ---------------- */
const ACTION_TEXT = {
  walk: "正在走向…",
  drink: "正在喝酒…",
  toast: "举杯致意…",
  wipe: "正在擦吧台…",
  idle: "站在吧台前",
};
const SCRIPT = [
  { action: "walk", to: { x: 3.3, z: 0.4 }, text: "走进酒吧，来到吧台" },
  { action: "drink", dur: 6, text: "在吧台端起酒杯喝一杯" },
  { action: "walk", to: { x: -1.4, z: -1.2 }, text: "端着酒杯走向 1 号桌" },
  { action: "toast", dur: 3, text: "举起酒杯，向四周致意" },
  { action: "drink", dur: 4, text: "在桌边小酌" },
  { action: "walk", to: { x: 3.3, z: 0.4 }, text: "回到吧台" },
  { action: "wipe", dur: 5, text: "放下酒杯，擦了擦吧台" },
  { action: "idle", at: { x: 3.3, z: 0.4 }, dur: 8, text: "靠在吧台，听音乐等打烊" },
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function toastOnce() {
  const t0 = performance.now();
  if (clink) { clink.currentTime = 0; clink.play().catch(() => {}); }
  // 举杯致意 → 稍作停顿 → 放下
  while (performance.now() - t0 < 900) {
    toastT = (performance.now() - t0) / 900;
    await sleep(16);
  }
  toastT = 1;
  await sleep(1400);
  while (performance.now() - t0 < 2200) {
    toastT = 1 - (performance.now() - t0 - 900 - 1300) / 900;
    await sleep(16);
  }
  toastT = 0;
}

async function drinkOnce() {
  const t0 = performance.now();
  // 举杯
  while (performance.now() - t0 < 1400) {
    drinkT = (performance.now() - t0) / 1400;
    await sleep(16);
  }
  drinkT = 1;
  await sleep(1200);
  // 放下
  while (performance.now() - t0 < 2400) {
    drinkT = 1 - (performance.now() - t0 - 1400 - 1000) / 1000;
    await sleep(16);
  }
  drinkT = 0;
}

async function startScript() {
  await sleep(500);
  while (true) {
    for (const step of SCRIPT) {
      actionEl.textContent = step.text || ACTION_TEXT[step.action] || "";
      if (step.action === "walk") {
        state = "walk";
        charTarget = step.to;
        await new Promise((res) => { walkResolve = res; });
      } else if (step.action === "drink") {
        state = "drink";
        if (clink) { clink.currentTime = 0; clink.play().catch(() => {}); }
        await drinkOnce();
        await sleep(Math.max(0, (step.dur - 3.4) * 1000));
      } else if (step.action === "toast") {
        state = "toast";
        await toastOnce();
        await sleep(Math.max(0, (step.dur - 2.2) * 1000));
      } else {
        state = step.action;
        await sleep(step.dur * 1000);
      }
    }
    actionEl.textContent = "（循环）";
    await sleep(2500);
  }
}

/* ---------------- 音频 ---------------- */
function setupAudio(a) {
  if (a.music) {
    music = new Audio(a.music.url);
    music.loop = true;
    music.volume = 0.45;
    listEl.appendChild(item("背景音乐", a.music.filename));
  }
  const sfxList = (a.sfx || []).filter(Boolean);
  if (sfxList.length) {
    const glass = sfxList.find((s) => /glass|clink/i.test(s.filename));
    const amb = sfxList.find((s) => /ambient|murmur|环境/i.test(s.filename));
    clink = glass ? new Audio(glass.url) : null;
    if (clink) clink.volume = 0.65;
    ambient = amb ? new Audio(amb.url) : null;
    if (ambient) { ambient.loop = true; ambient.volume = 0.2; }
    sfxList.forEach((s) => listEl.appendChild(item("环境音效", s.filename)));
  }
}

async function buildScene(a) {
  if (!webglOK) {
    await fallback2D(a);
    return;
  }
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0d0a);
  scene.fog = new THREE.FogExp2(0x0b0d0a, 0.05);
  scene.add(new THREE.HemisphereLight(0x8899bb, 0x332211, 0.95));
  scene.add(new THREE.AmbientLight(0x556677, 0.7));
  const dir = new THREE.DirectionalLight(0xffeedd, 1.0);
  dir.position.set(4, 8, 5);
  scene.add(dir);

  buildRoom(a);
  await buildCharacter(a);
  setupAudio(a);
  assetsEl.textContent = `共 ${listEl.children.length} 项资产`;
  soundBtn.classList.remove("hidden");
  startScript();
}

function item(kind, name) {
  const li = document.createElement("li");
  li.textContent = `▪ ${kind}: ${name}`;
  return li;
}

function startAudio() {
  if (soundOn) return;
  soundOn = true;
  if (music) music.play().catch(() => {});
  if (ambient) ambient.play().catch(() => {});
  clinkTimer = setInterval(() => {
    if (clink) { clink.currentTime = 0; clink.play().catch(() => {}); }
  }, 6000 + Math.random() * 4000);
}

function stopAudio() {
  soundOn = false;
  [music, ambient].forEach((a) => a && a.pause());
  clearInterval(clinkTimer);
}

if (!batch) {
  overlay.classList.add("hidden");
  statusEl.textContent = "缺少 batch 参数（从任务详情进入）";
}
overlay.addEventListener("click", () => {
  startAudio();
  overlay.classList.add("hidden");
});
soundBtn.addEventListener("click", () => {
  if (soundOn) { stopAudio(); soundBtn.textContent = "音效开/关（当前关）"; }
  else { startAudio(); soundBtn.textContent = "音效开/关（当前开）"; }
});

/* ---------------- 2D 兼容模式（WebGL 不可用时自动启用） ---------------- */
let fbCtx = null, fbCanvas = null, fbBg = null, fbAtlas = null, fbCfg = null;
let fbMouse = { x: 0, y: 0 }, fbFrame = 0, fbFacing = 1, fbX = 0.8, fbTarget = null;
const fbDust = Array.from({ length: 120 }, () => ({
  x: Math.random(), y: Math.random() * 0.6, s: 0.4 + Math.random() * 0.6,
}));

function loadImg(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片加载失败: " + url));
    img.src = url;
  });
}

async function fallback2D(a) {
  overlay.classList.add("hidden");
  statusEl.textContent = "2D 兼容模式（当前环境不支持 WebGL）· 拖拽移动视角";
  fbCanvas = document.createElement("canvas");
  fbCanvas.style.width = "100%";
  fbCanvas.style.height = "100%";
  document.getElementById("canvas-wrap").appendChild(fbCanvas);
  fbCtx = fbCanvas.getContext("2d");
  fbCfg = a.sprite_config;
  try {
    if (a.concept) fbBg = await loadImg(a.concept.url);
    if (a.atlas) fbAtlas = await loadImg(a.atlas.url);
  } catch (err) {
    statusEl.textContent = err.message;
  }
  addEventListener("mousemove", (e) => {
    fbMouse.x = (e.clientX / innerWidth - 0.5) * 2;
    fbMouse.y = (e.clientY / innerHeight - 0.5) * 2;
  });
  setupAudio(a);
  assetsEl.textContent = `共 ${listEl.children.length} 项资产`;
  soundBtn.classList.remove("hidden");
  fbLoop();
  fbScript();
}

function fbLoop() {
  const ctx = fbCtx, w = (fbCanvas.width = innerWidth), h = (fbCanvas.height = innerHeight);
  ctx.fillStyle = "#0b0d0a";
  ctx.fillRect(0, 0, w, h);
  // 背景图视差（覆盖式）
  if (fbBg) {
    const k = Math.max(w / fbBg.width, h / fbBg.height) * 1.08;
    const bw = fbBg.width * k, bh = fbBg.height * k;
    const ox = -(fbMouse.x * 22 + 10) + (w - bw) / 2;
    const oy = -(fbMouse.y * 14 + 8) + (h - bh) / 2;
    ctx.drawImage(fbBg, ox, oy, bw, bh);
    const grd = ctx.createLinearGradient(0, h * 0.55, 0, h);
    grd.addColorStop(0, "rgba(8,10,7,0)");
    grd.addColorStop(1, "rgba(8,10,7,0.85)");
    ctx.fillStyle = grd;
    ctx.fillRect(0, h * 0.55, w, h * 0.45);
  } else {
    ctx.fillStyle = "#14160f";
    ctx.fillRect(0, 0, w, h);
  }
  // 灰尘
  ctx.fillStyle = "rgba(204,187,153,0.5)";
  fbDust.forEach((d) => {
    d.y -= 0.00018 * d.s;
    if (d.y < -0.02) d.y = 1.02;
    ctx.beginPath();
    ctx.arc(d.x * w, d.y * h, 1.2 * d.s, 0, Math.PI * 2);
    ctx.fill();
  });
  // 角色（贴地 + 阴影）
  if (fbAtlas && fbCfg) {
    const cx = (fbX * 0.7 + 0.15) * w;
    const groundY = h * 0.82;
    const ch = h * 0.42, cw = ch;
    ctx.fillStyle = "rgba(0,0,0,0.4)";
    ctx.beginPath();
    ctx.ellipse(cx, groundY + ch * 0.02, cw * 0.28, cw * 0.06, 0, 0, Math.PI * 2);
    ctx.fill();
    const row = Math.floor(fbFrame / fbCfg.columns);
    const col = fbFrame % fbCfg.columns;
    const cellW = fbAtlas.width / fbCfg.columns;
    const cellH = fbAtlas.height / fbCfg.rows;
    ctx.save();
    ctx.translate(cx, groundY);
    ctx.scale(fbFacing, 1);
    ctx.drawImage(fbAtlas, col * cellW, row * cellH, cellW, cellH, -cw / 2, -ch, cw, ch);
    ctx.restore();
  }
  requestAnimationFrame(fbLoop);
}

function fbScript() {
  const way = [
    { x: 0.88, dur: 6000, text: "酒保在吧台后擦洗玻璃杯" },
    { x: 0.58, dur: 2600, text: "从吧台走出来" },
    { x: 0.24, dur: 2600, text: "走向 1 号桌" },
    { x: 0.24, dur: 5000, text: "收拾 1 号桌的酒杯" },
    { x: 0.24, dur: 1, text: "" },
    { x: 0.42, dur: 2600, text: "走向 2 号桌" },
    { x: 0.42, dur: 5000, text: "擦 2 号桌台面" },
    { x: 0.88, dur: 2600, text: "回到吧台" },
    { x: 0.88, dur: 8000, text: "在吧台后待机，等待打烊" },
  ];
  let i = 0;
  setInterval(() => {
    const step = way[i];
    actionEl.textContent = step.text || "";
    fbTarget = step.x;
    fbFacing = step.x > fbX ? 1 : -1;
    const steps = Math.max(1, Math.round(step.dur / 60));
    let moved = 0;
    const timer = setInterval(() => {
      moved++;
      const t = moved / steps;
      fbX = fbTarget - (fbTarget - (i === 0 ? 0.88 : fbX)) * (1 - t);
      if (moved >= steps) clearInterval(timer);
    }, 16);
    i = (i + 1) % way.length;
    if (fbCfg) fbFrame = (fbFrame + 1) % fbCfg.frames;
  }, 100);
}
