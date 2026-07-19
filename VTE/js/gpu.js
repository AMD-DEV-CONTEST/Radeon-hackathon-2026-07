/* ===================================================================
   gpu.js — RX 7600 estilizada em 3D que se DESMONTA conforme o scroll
   (exploded view scroll-driven). Cada passo destaca uma peça com a qual
   o VTE conversa e troca o card de info. Construída com primitivas do
   Three.js (sem asset externo) — reconhecível como uma placa de vídeo:
   PCB verde, shroud com 2 fans, die central (32 CUs), 4 chips de VRAM,
   conector PCIe dourado-esverdeado, conector de energia, backplate.
   Só verde + neutros (sem azul/roxo).
   =================================================================== */
(function () {
  "use strict";

  var canvas = document.getElementById("gpu-canvas");
  var section = document.getElementById("placa");
  if (!canvas || !section || typeof THREE === "undefined") return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var GREEN = 0x32f08c, DIM = 0x1bbd6d, DEEP = 0x0a6b45;

  // ---- Passos (peça + info) ----
  var STEPS = [
    {
      key: "board",
      step: "01 / 05 · RX 7600",
      title: "RDNA3 · gfx1102 · 8 GB",
      desc: "A placa de consumidor onde tudo foi construído e medido. 32 Compute Units, 8 GB de GDDR6, dividida com o resto do desktop. Role para ver cada peça com que o VTE conversa.",
    },
    {
      key: "sensors",
      step: "02 / 05 · ADL (Sensores)",
      title: "ADL · duty-cycle",
      desc: "A temperatura real vem da ADL (atiadlxx.dll). Um limitador de duty-cycle segura a utilização perto de 95% pra não travar o resto do desktop durante gerações longas.",
    },
    {
      key: "die",
      step: "03 / 05 · Chipset / Die",
      title: "Navi 33 · 32 Compute Units",
      desc: "Onde os kernels HIP gerados e compilados em runtime realmente rodam. O VTE preenche os 32 CUs com fusão Split-K em vez de deixar a maioria ociosa.",
    },
    {
      key: "vram",
      step: "04 / 05 · VRAM",
      title: "8 GB GDDR6",
      desc: "O SlabAllocator faz um único hipMalloc gigante e sub-aloca tudo — pesos, KV cache, arena de ativação — dentro dele, sem fragmentação durante a geração.",
    },
    {
      key: "pcie",
      step: "05 / 05 · BAR (PCIe)",
      title: "Barramento host ↔ device",
      desc: "Uploads de pesos são fatiados em blocos ≤16 MB. Um hipMemcpy gigante de uma vez dispararia o TDR do WDDM — o VTE dá janelas ao driver entre as transferências.",
    },
  ];

  // ---- Three.js base ----
  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  var BASE_DIST = 9; // distância "de fábrica", ajustada olhando pra um viewport widescreen
  // A placa tem ~7 unidades de largura (mais ~2.6 quando explode no scroll). Com FOV
  // vertical fixo, o FOV HORIZONTAL efetivo é proporcional ao aspect ratio -- numa tela
  // em retrato (mobile, aspect ~0.46) ele encolhe bastante, então a mesma distância de
  // câmera deixa a placa ocupando muito mais da largura da tela (o "grande demais" /
  // cortado embaixo reportado no mobile). BASE_HALF_WIDTH congela o meio-largura visível
  // que BASE_DIST produzia no aspect de referência (1.6, desktop widescreen) -- resize()
  // usa isso pra recuar a câmera em telas mais estreitas, preservando a mesma largura
  // visível em vez da mesma distância.
  var BASE_HALF_WIDTH = BASE_DIST * Math.tan((camera.fov * Math.PI) / 360) * 1.6;
  camera.position.set(0, 0.4, BASE_DIST);
  // A câmera nunca teve um lookAt(): sem ele, olha reto no eixo -Z (nível,
  // não inclinada pra baixo), então com a câmera em y=2.2 e a placa toda
  // perto de y=0, a placa inteira cai na metade DE BAIXO do frame -- é por
  // isso que ela aparecia cortada embaixo (desktop). O card de texto
  // (`.gpu-info`) fica na metade de baixo da tela por CSS -- a placa
  // precisa ficar deslocada pra CIMA da tela, não centralizada nela, senão
  // fica atrás do próprio card (o que aconteceu ao mirar num Y fixo).
  // Um Y de mira fixo não funciona: a distância da câmera varia MUITO
  // entre desktop (~9) e mobile (~30+, ver resize() abaixo), e o mesmo
  // deslocamento vertical em unidades de mundo produz um deslocamento de
  // TELA bem menor quanto mais longe a câmera está. Por isso o alvo de
  // mira é recalculado em função da distância atual (BOARD_CENTER_Y menos
  // um deslocamento proporcional à distância vezes tan(TILT_UP_RAD)),
  // mantendo o mesmo deslocamento ANGULAR -- e portanto a mesma posição
  // relativa na tela -- em qualquer aspect ratio. Ver resize().
  var BOARD_CENTER_Y = -0.4; // GPU mais centrada/baixa na tela
  var TILT_UP_RAD = (2 * Math.PI) / 180;
  function aimCamera(dist) {
    camera.lookAt(0, BOARD_CENTER_Y - dist * Math.tan(TILT_UP_RAD), 0);
  }
  aimCamera(BASE_DIST);

  var renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  var card = new THREE.Group();
  card.position.y = -0.7; // desloca o grupo todo para baixo
  scene.add(card);

  // Materiais reutilizáveis
  function mat(color, opts) {
    opts = opts || {};
    return new THREE.MeshStandardMaterial({
      color: color,
      emissive: opts.emissive !== undefined ? opts.emissive : 0x000000,
      emissiveIntensity: opts.ei || 0,
      metalness: opts.metal !== undefined ? opts.metal : 0.6,
      roughness: opts.rough !== undefined ? opts.rough : 0.5,
    });
  }
  function edgesOf(geo, color, opacity) {
    return new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: opacity })
    );
  }

  // Cada peça: { mesh, home (pos base), dir (vetor de explosão), group } com userData.
  var parts = [];
  function addPart(mesh, home, dir, groupKey, baseEI) {
    mesh.position.copy(home);
    mesh.userData = { home: home.clone(), dir: dir.clone(), groupKey: groupKey, baseEI: baseEI || 0 };
    card.add(mesh);
    parts.push(mesh);
    return mesh;
  }

  var V = THREE.Vector3;

  // ---- PCB (base, âncora) ----
  var pcbGeo = new THREE.BoxGeometry(7, 0.14, 3);
  var pcb = new THREE.Mesh(pcbGeo, mat(0x07130d, { metal: 0.3, rough: 0.7 }));
  addPart(pcb, new V(0, 0, 0), new V(0, 0, 0), "board");
  var pcbEdge = edgesOf(pcbGeo, GREEN, 0.4);
  pcb.add(pcbEdge);

  // Trilhas verdes na PCB (linhas)
  var traceMat = new THREE.LineBasicMaterial({ color: DIM, transparent: true, opacity: 0.4 });
  var tg = new THREE.BufferGeometry();
  var tpts = [];
  for (var i = 0; i < 18; i++) {
    var z = -1.3 + Math.random() * 2.6;
    tpts.push(-3.4, 0.08, z, 3.4, 0.08, z);
  }
  tg.setAttribute("position", new THREE.Float32BufferAttribute(tpts, 3));
  pcb.add(new THREE.LineSegments(tg, traceMat));

  // ---- GPU die (Navi 33 package) ----
  var die = new THREE.Group();
  
  // 1. Substrato prata (base)
  var pkgBaseGeo = new THREE.BoxGeometry(1.8, 0.04, 1.8);
  var pkgBase = new THREE.Mesh(pkgBaseGeo, mat(0x9fa4a9, { metal: 0.4, rough: 0.6 }));
  pkgBase.position.y = 0.02;
  die.add(pkgBase);

  // 2. Interposer verde escuro
  var interposerGeo = new THREE.BoxGeometry(1.2, 0.02, 1.2);
  var interposer = new THREE.Mesh(interposerGeo, mat(0x0f2a1a, { metal: 0.2, rough: 0.8 }));
  interposer.position.y = 0.05;
  die.add(interposer);

  // 3. Silicon die (cristal central girado 45 graus)
  var siliconGeo = new THREE.BoxGeometry(0.75, 0.04, 0.75);
  var siliconMat = mat(0x3a4b5c, { metal: 0.9, rough: 0.15 });
  // Passamos emissive para o material do silicon caso a lógica de destaque precise interagir,
  // mas o brilho principal virá dos CUs.
  siliconMat.emissive.setHex(0x000000); 
  var silicon = new THREE.Mesh(siliconGeo, siliconMat);
  silicon.position.y = 0.08;
  silicon.rotation.y = Math.PI / 4; // rotaciona 45 graus (forma de diamante)
  die.add(silicon);

  // Adicionamos a borda verde do cristal para destaque
  silicon.add(edgesOf(siliconGeo, GREEN, 0.4));

  // O grupo "die" inteiro deve ficar grudado na PCB ao explodir
  addPart(die, new V(-0.4, 0.07, 0), new V(0, 0, 0), "die");

  // mini grade 8x4 de CUs no topo do cristal de silício
  var cuCells = [];
  var cuGeo = new THREE.BoxGeometry(0.06, 0.02, 0.06);
  for (var r = 0; r < 4; r++) {
    for (var c = 0; c < 8; c++) {
      var cu = new THREE.Mesh(cuGeo, mat(0x112218, { emissive: GREEN, ei: 0.1 }));
      // As coordenadas são relativas ao silicon (que já está girado 45 graus)
      cu.position.set(-0.28 + c * 0.08, 0.025, -0.12 + r * 0.08);
      cu.userData.phase = Math.random() * Math.PI * 2;
      silicon.add(cu);
      cuCells.push(cu);
    }
  }

  // ---- VRAM (4 chips ao redor do die) ----
  var vramMeshes = [];
  var vramGeo = new THREE.BoxGeometry(0.7, 0.16, 0.5);
  var vramHomes = [
    new V(1.4, 0.16, -0.7), new V(1.4, 0.16, 0.7),
    new V(1.4, 0.16, 0), new V(-0.4, 0.16, 1.05),
  ];
  var vramDirs = [
    new V(0.9, 0.4, -0.5), new V(0.9, 0.4, 0.5),
    new V(1.1, 0.5, 0), new V(-0.2, 0.5, 1),
  ];
  for (var v = 0; v < 4; v++) {
    var vr = new THREE.Mesh(vramGeo, mat(0x101317, { emissive: GREEN, ei: 0.04, metal: 0.7 }));
    addPart(vr, vramHomes[v], vramDirs[v].normalize(), "vram", 0.04);
    vr.add(edgesOf(vramGeo, DIM, 0.5));
    vramMeshes.push(vr);
  }

  // ---- Conector PCIe (contatos na borda inferior) ----
  var pcieGeo = new THREE.BoxGeometry(3.2, 0.1, 0.5);
  var pcie = new THREE.Mesh(pcieGeo, mat(0x1a2f22, { emissive: GREEN, ei: 0.15, metal: 0.85, rough: 0.35 }));
  addPart(pcie, new V(-0.8, -0.02, 1.65), new V(0, -0.6, 1), "pcie", 0.15);
  // "dentes" dos contatos (z=0.52 para evitar z-fighting com o conector z=0.5)
  for (var t = 0; t < 14; t++) {
    var tooth = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.12, 0.52), mat(0x244a35, { emissive: GREEN, ei: 0.25 }));
    tooth.position.set(-1.45 + t * 0.22, 0.02, 0);
    pcie.add(tooth);
  }

  // ---- Conector de energia (8-pin, borda superior) ----
  var pwrGeo = new THREE.BoxGeometry(0.9, 0.32, 0.45);
  var pwr = new THREE.Mesh(pwrGeo, mat(0x0a0b0c, { metal: 0.6 }));
  addPart(pwr, new V(2.6, 0.2, -1.05), new V(0.6, 0.7, -0.6).normalize(), "sensors", 0);
  pwr.add(edgesOf(pwrGeo, DIM, 0.5));

  // ---- Shroud + backplate + fans (cooler) ----
  var shroudGeo = new THREE.BoxGeometry(7, 0.5, 3);
  var shroud = new THREE.Mesh(shroudGeo, mat(0x0a0b0c, { metal: 0.7, rough: 0.4 }));
  addPart(shroud, new V(0, 0.9, 0), new V(0, 1, 0), "sensors", 0);
  shroud.add(edgesOf(shroudGeo, GREEN, 0.28));

  var fanMeshes = [];
  var fanGeo = new THREE.CylinderGeometry(1.1, 1.1, 0.12, 28);
  var fanPos = [new V(-1.7, 0.28, 0), new V(1.7, 0.28, 0)];
  for (var f = 0; f < 2; f++) {
    var fan = new THREE.Mesh(fanGeo, mat(0x0d0f11, { metal: 0.5 }));
    // pás (curvas e varridas)
    var bladeCount = 9;
    var S = 0.95; // Escala para caber no cilindro de raio 1.1
    for (var b = 0; b < bladeCount; b++) {
      var angle = (b / bladeCount) * Math.PI * 2;
      
      var bs = new THREE.Shape();
      bs.moveTo(0, 0.15 * S);
      // Borda de ataque
      bs.bezierCurveTo(0.15 * S, 0.40 * S, 0.50 * S, 0.46 * S, 0.62 * S, 0.72 * S);
      // Ponta externa arredondada (limitada ao raio)
      bs.bezierCurveTo(0.66 * S, 0.95 * S, 0.56 * S, 1.05 * S, 0.44 * S, 1.05 * S);
      // Borda de fuga
      bs.bezierCurveTo(0.28 * S, 0.92 * S, 0.05 * S, 0.65 * S, 0, 0.15 * S);
      
      var bladeGeo = new THREE.ExtrudeGeometry(bs, {
        depth: 0.025, bevelEnabled: true,
        bevelThickness: 0.005, bevelSize: 0.004, bevelSegments: 1
      });
      bladeGeo.rotateX(-Math.PI / 2);
      
      var blade = new THREE.Mesh(bladeGeo, mat(0x141a17, { emissive: DEEP, ei: 0.2 }));
      blade.rotation.y = angle;
      blade.position.y = 0.03;
      fan.add(blade);
    }
    fan.add(edgesOf(new THREE.CylinderGeometry(1.1, 1.1, 0.12, 28), GREEN, 0.3));
    shroud.add(fan);
    fan.position.copy(fanPos[f]);
    fanMeshes.push(fan);
  }

  var backGeo = new THREE.BoxGeometry(7, 0.08, 3);
  var back = new THREE.Mesh(backGeo, mat(0x060708, { metal: 0.8, rough: 0.4 }));
  addPart(back, new V(0, -0.16, 0), new V(0, -1, 0), "board");
  back.add(edgesOf(backGeo, DIM, 0.25));

  // ---- Luzes ----
  scene.add(new THREE.AmbientLight(0x384038, 1.15));
  var key = new THREE.PointLight(GREEN, 1.5, 30); key.position.set(4, 6, 5); scene.add(key);
  var rim = new THREE.PointLight(DIM, 0.7, 30); rim.position.set(-5, 3, -3); scene.add(rim);
  var fill = new THREE.PointLight(DEEP, 0.6, 30); fill.position.set(0, -4, 4); scene.add(fill);

  // Targets para a seta SVG
  var connectorTargets = {
    "board": pcb,
    "die": die,
    "vram": vramMeshes[0],
    "pcie": pcie,
    "sensors": fanMeshes[0]
  };

  // ---- Estado de scroll ----
  var progress = 0;      // 0..1 ao longo da seção
  var activeStep = 0;
  var active = false;    // seção perto da viewport?

  function easeInOut(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

  function onScroll() {
    var rect = section.getBoundingClientRect();
    var vh = window.innerHeight;
    var total = section.offsetHeight - vh;
    var scrolled = Math.min(Math.max(-rect.top, 0), total);
    progress = total > 0 ? scrolled / total : 0;
    active = rect.top < vh && rect.bottom > 0;

    var idx = Math.min(STEPS.length - 1, Math.floor(progress * STEPS.length));
    if (idx !== activeStep) { activeStep = idx; updateInfo(idx); }
    updateProgressDots(idx);

    var hint = document.getElementById("gpu-hint");
    if (hint) hint.style.opacity = progress > 0.04 ? "0" : "1";
  }
  window.addEventListener("scroll", onScroll, { passive: true });

  // ---- Seta conectora (projeta componente ativo para coords de tela) ----
  var connectorSvg   = document.getElementById("gpu-connector");
  var connectorLine  = document.getElementById("connector-line");
  var connectorDot   = document.getElementById("connector-dot");
  var connectorPulse = document.getElementById("connector-pulse");
  var infoCard       = document.getElementById("gpu-info-card");
  var tempV = new THREE.Vector3();
  var cachedCanvasRect = null;
  var cachedCardRect   = null;
  function refreshRects() {
    cachedCanvasRect = renderer.domElement.getBoundingClientRect();
    if (infoCard) cachedCardRect = infoCard.getBoundingClientRect();
  }
  window.addEventListener("resize",  refreshRects, { passive: true });
  window.addEventListener("scroll",  refreshRects, { passive: true });



  function updateConnector(t) {
    if (!connectorSvg || !infoCard || activeStep === 0 || !active) {
      if (connectorSvg) connectorSvg.style.opacity = "0";
      return;
    }
    if (!cachedCanvasRect || !cachedCardRect) refreshRects();

    // pick the part to point at based on active step key
    var key = STEPS[activeStep].key;
    var target = connectorTargets[key];
    if (!target) { connectorSvg.style.opacity = "0"; return; }

    target.getWorldPosition(tempV);
    tempV.project(camera);
    var cw = renderer.domElement.clientWidth;
    var ch = renderer.domElement.clientHeight;
    var toX = (tempV.x *  0.5 + 0.5) * cw;
    var toY = (tempV.y * -0.5 + 0.5) * ch;

    var isMobile = cw <= 720;
    var fromX, fromY;
    if (!isMobile) {
      fromX = cachedCardRect.left - 15 - cachedCanvasRect.left;
      fromY = cachedCardRect.top + cachedCardRect.height / 2 - cachedCanvasRect.top;
    } else {
      fromX = cachedCardRect.left + cachedCardRect.width / 2 - cachedCanvasRect.left;
      fromY = cachedCardRect.top  - cachedCanvasRect.top;
    }

    var midX = (fromX + toX) / 2;
    var pathData = "M" + fromX + "," + fromY + " Q" + midX + "," + fromY + " " + toX + "," + toY;
    connectorLine.setAttribute("d", pathData);
    connectorDot.setAttribute("cx", toX);
    connectorDot.setAttribute("cy", toY);
    connectorPulse.setAttribute("cx", toX);
    connectorPulse.setAttribute("cy", toY);
    var pulse = (t * 2) % 1;
    connectorPulse.setAttribute("r",  5 + pulse * 10);
    connectorPulse.setAttribute("stroke-opacity", (1 - pulse).toFixed(2));
    connectorSvg.style.opacity = "1";
  }

  // ---- Info card swap ----
  var swap = document.getElementById("gpu-swap");
  var stepEl = document.getElementById("gpu-step");
  var titleEl = document.getElementById("gpu-title");
  var descEl = document.getElementById("gpu-desc");
  function updateInfo(idx) {
    if (!swap) return;
    swap.classList.add("out");
    setTimeout(function () {
      stepEl.textContent = STEPS[idx].step;
      titleEl.textContent = STEPS[idx].title;
      descEl.textContent = STEPS[idx].desc;
      swap.classList.remove("out");
    }, 220);
  }
  function updateProgressDots(idx) {
    var dots = document.querySelectorAll("#gpu-progress i");
    for (var i = 0; i < dots.length; i++) dots[i].classList.toggle("on", i === idx);
  }

  // ---- Resize ----
  function resize() {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    var aspect = w / h;
    camera.aspect = aspect;

    var vFovRad = (camera.fov * Math.PI) / 180;
    var distForWidth = BASE_HALF_WIDTH / (Math.tan(vFovRad / 2) * aspect);
    camera.position.z = Math.max(BASE_DIST, distForWidth);
    aimCamera(camera.position.z); // recalcula o alvo pra manter o mesmo deslocamento ANGULAR
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);
  resize();
  onScroll();

  // ---- Loop ----
  var tmp = new THREE.Vector3();
  function frame(now) {
    requestAnimationFrame(frame);
    if (!active && progress > 0 && progress < 1) { /* ainda renderiza 1x */ }
    if (!active) { return; }

    var t = now / 1000;
    var explode = easeInOut(progress);

    // gira conforme desmonta; mantém rotation.x fixo para a GPU não subir
    card.rotation.y = -0.5 + progress * 1.6 + Math.sin(t * 0.15) * 0.05;
    card.rotation.x = 0.25;
    // compensa a subida causada pela explosão dos vetores com Y positivo
    card.position.y = -0.7 - explode * 0.35;

    // move cada peça: home + dir * explode * distância
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      var d = p.userData;
      var dist = 1.8;
      tmp.copy(d.dir).multiplyScalar(explode * dist);
      p.position.copy(d.home).add(tmp);

      // destaque da peça do passo ativo
      var isActive = d.groupKey === STEPS[activeStep].key;
      var targetEI = d.baseEI + (isActive ? 0.5 : 0);
      if (p.material && p.material.emissive) {
        p.material.emissiveIntensity += (targetEI - p.material.emissiveIntensity) * 0.1;
        p.material.emissive.setHex(isActive ? GREEN : (d.baseEI > 0 ? GREEN : 0x000000));
      }
      // peças não-ativas ficam levemente mais opacas/apagadas quando algo está destacado
    }

    // CUs pulsando (mais quando o die está ativo)
    var dieActive = STEPS[activeStep].key === "die";
    for (var k = 0; k < cuCells.length; k++) {
      var pulse = 0.08 + Math.max(0, Math.sin(t * 1.6 + cuCells[k].userData.phase)) * (dieActive ? 0.9 : 0.25);
      cuCells[k].material.emissiveIntensity = pulse;
    }

    // fans girando
    for (var ff = 0; ff < fanMeshes.length; ff++) fanMeshes[ff].rotation.y += 0.04;

    updateConnector(t);
    renderer.render(scene, camera);
  }

  if (reduceMotion) {
    // estado estático semi-explodido
    progress = 0; onScroll();
    card.rotation.set(0.25, -0.5, 0);
    renderer.render(scene, camera);
  } else {
    requestAnimationFrame(frame);
  }
})();
