/* ===================================================================
   scene.js — cena 3D do hero: um "die" de GPU visto de cima, com uma
   grade de 8×4 = 32 Compute Units (os 32 CUs reais da RX 7600) que
   pulsam como se estivessem processando trabalho. Parallax pelo mouse.
   Three.js r128 (global THREE, carregado via CDN no index.html).
   Sem postprocessing/bloom de propósito: emissive + additive dá o glow
   sem custo de EffectComposer, mantendo tudo leve.
   =================================================================== */
(function () {
  "use strict";

  var canvas = document.getElementById("chip-canvas");
  if (!canvas || typeof THREE === "undefined") return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var GREEN = 0x32f08c;
  var DEEP = 0x0a6b45; // verde escuro pra luz de preenchimento
  var DIM = 0x1bbd6d;  // verde intermediário

  var scene = new THREE.Scene();

  var camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 3.4, 6.2);
  camera.lookAt(0, 0, 0);

  var renderer = new THREE.WebGLRenderer({
    canvas: canvas,
    alpha: true,
    antialias: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // ---- Grupo raiz (tudo que gira junto) ----
  var chip = new THREE.Group();
  scene.add(chip);

  // ---- Substrato / die ----
  var dieGeo = new THREE.BoxGeometry(4.2, 0.28, 4.2);
  var dieMat = new THREE.MeshStandardMaterial({
    color: 0x0a0b0c,
    metalness: 0.9,
    roughness: 0.35,
  });
  var die = new THREE.Mesh(dieGeo, dieMat);
  chip.add(die);

  // Borda emissiva do die (wireframe)
  var edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(dieGeo),
    new THREE.LineBasicMaterial({ color: GREEN, transparent: true, opacity: 0.35 })
  );
  chip.add(edges);

  // ---- Grade de 32 Compute Units (8×4) ----
  var COLS = 8, ROWS = 4;
  var cellSize = 0.42, gap = 0.08;
  var totalW = COLS * cellSize + (COLS - 1) * gap;
  var totalD = ROWS * cellSize + (ROWS - 1) * gap;
  var cells = [];
  var cellGeo = new THREE.BoxGeometry(cellSize, 0.12, cellSize);

  for (var r = 0; r < ROWS; r++) {
    for (var c = 0; c < COLS; c++) {
      var mat = new THREE.MeshStandardMaterial({
        color: 0x0d1a14,
        emissive: GREEN,
        emissiveIntensity: 0.08,
        metalness: 0.6,
        roughness: 0.4,
      });
      var cell = new THREE.Mesh(cellGeo, mat);
      cell.position.x = -totalW / 2 + cellSize / 2 + c * (cellSize + gap);
      cell.position.z = -totalD / 2 + cellSize / 2 + r * (cellSize + gap);
      cell.position.y = 0.2;
      // fase aleatória pra cada CU pulsar em tempos diferentes
      cell.userData.phase = Math.random() * Math.PI * 2;
      cell.userData.speed = 0.8 + Math.random() * 1.6;
      chip.add(cell);
      cells.push(cell);
    }
  }

  // ---- "Trilhas" de dados (linhas emissivas entre bordas) ----
  var traceMat = new THREE.LineBasicMaterial({ color: DIM, transparent: true, opacity: 0.28 });
  var traceGeo = new THREE.BufferGeometry();
  var tracePts = [];
  for (var i = 0; i < 14; i++) {
    var x = -totalW / 2 - 0.4 + Math.random() * (totalW + 0.8);
    tracePts.push(x, 0.16, -totalD / 2 - 0.3);
    tracePts.push(x, 0.16, totalD / 2 + 0.3);
  }
  traceGeo.setAttribute("position", new THREE.Float32BufferAttribute(tracePts, 3));
  chip.add(new THREE.LineSegments(traceGeo, traceMat));

  // ---- Partículas flutuando ao redor (additive glow) ----
  var pGeo = new THREE.BufferGeometry();
  var pCount = 140;
  var pPos = new Float32Array(pCount * 3);
  for (var p = 0; p < pCount; p++) {
    pPos[p * 3] = (Math.random() - 0.5) * 12;
    pPos[p * 3 + 1] = Math.random() * 6 - 1;
    pPos[p * 3 + 2] = (Math.random() - 0.5) * 12;
  }
  pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
  var pMat = new THREE.PointsMaterial({
    color: GREEN,
    size: 0.045,
    transparent: true,
    opacity: 0.7,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  var particles = new THREE.Points(pGeo, pMat);
  scene.add(particles);

  // ---- Luzes ----
  scene.add(new THREE.AmbientLight(0x404050, 1.1));
  var key = new THREE.PointLight(GREEN, 1.4, 20);
  key.position.set(3, 5, 3);
  scene.add(key);
  var rim = new THREE.PointLight(DIM, 0.6, 20);
  rim.position.set(-4, 2, -3);
  scene.add(rim);
  var fill = new THREE.PointLight(DEEP, 0.7, 22);
  fill.position.set(0, -3, 4);
  scene.add(fill);

  // ---- Interação: parallax pelo mouse ----
  var targetRX = 0, targetRY = 0;
  window.addEventListener("mousemove", function (e) {
    var nx = (e.clientX / window.innerWidth) * 2 - 1;
    var ny = (e.clientY / window.innerHeight) * 2 - 1;
    targetRY = nx * 0.5;
    targetRX = ny * 0.25;
  });

  // ---- Resize ----
  function resize() {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);
  resize();

  // ---- Loop ----
  var t0 = performance.now();
  var visible = true;
  document.addEventListener("visibilitychange", function () {
    visible = !document.hidden;
    if (visible) requestAnimationFrame(loop);
  });

  function loop() {
    if (!visible) return;
    var t = (performance.now() - t0) / 1000;

    // rotação base + parallax suave
    chip.rotation.y += 0.0016;
    chip.rotation.x += (targetRX + 0.32 - chip.rotation.x) * 0.05;
    chip.rotation.y += (targetRY - (chip.rotation.y % (Math.PI * 2)) * 0) * 0.0; // (y já acumula)
    chip.rotation.z = Math.sin(t * 0.2) * 0.02;

    // CUs pulsando
    for (var k = 0; k < cells.length; k++) {
      var cd = cells[k].userData;
      var pulse = 0.08 + Math.max(0, Math.sin(t * cd.speed + cd.phase)) * 0.9;
      cells[k].material.emissiveIntensity = pulse;
      cells[k].position.y = 0.2 + pulse * 0.04;
    }

    // partículas subindo devagar
    var arr = pGeo.attributes.position.array;
    for (var j = 1; j < arr.length; j += 3) {
      arr[j] += 0.004;
      if (arr[j] > 5) arr[j] = -1;
    }
    pGeo.attributes.position.needsUpdate = true;
    particles.rotation.y = t * 0.02;

    renderer.render(scene, camera);
    if (!reduceMotion) requestAnimationFrame(loop);
  }

  if (reduceMotion) {
    // desenha um único frame estático
    chip.rotation.x = 0.32;
    renderer.render(scene, camera);
  } else {
    requestAnimationFrame(loop);
  }
})();
