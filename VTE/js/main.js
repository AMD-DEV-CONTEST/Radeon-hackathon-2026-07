/* ===================================================================
   main.js — interações da landing (efeitos estilo MagicUI em JS puro):
   - reveal on scroll (IntersectionObserver)
   - number ticker (contagem animada dos stats)
   - animação das barras de benchmark ao entrar na viewport
   - meteors gerados dinamicamente
   - partículas de fundo (canvas 2D, camada global)
   =================================================================== */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Reveal on scroll ---------- */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var revObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            en.target.classList.add("is-visible");
            revObs.unobserve(en.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );
    revealEls.forEach(function (el, i) {
      // pequeno stagger entre irmãos
      el.style.transitionDelay = (i % 6) * 60 + "ms";
      revObs.observe(el);
    });
  } else {
    revealEls.forEach(function (el) { el.classList.add("is-visible"); });
  }

  /* ---------- Number ticker ---------- */
  function animateNumber(el) {
    var target = parseFloat(el.getAttribute("data-target"));
    var suffix = el.getAttribute("data-suffix") || "";
    var decimals = parseInt(el.getAttribute("data-decimals") || "0", 10);
    var dur = 1500;
    var start = performance.now();

    function step(now) {
      var t = Math.min((now - start) / dur, 1);
      // easeOutExpo
      var eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      var val = (target * eased).toFixed(decimals);
      el.textContent = val + suffix;
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = target.toFixed(decimals) + suffix;
    }
    requestAnimationFrame(step);
  }

  var numEls = document.querySelectorAll(".stat-num");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var numObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            animateNumber(en.target);
            numObs.unobserve(en.target);
          }
        });
      },
      { threshold: 0.6 }
    );
    numEls.forEach(function (el) { numObs.observe(el); });
  } else {
    numEls.forEach(function (el) {
      var d = parseInt(el.getAttribute("data-decimals") || "0", 10);
      el.textContent = parseFloat(el.getAttribute("data-target")).toFixed(d) + (el.getAttribute("data-suffix") || "");
    });
  }

  /* ---------- Barras de benchmark ---------- */
  var benchFills = document.querySelectorAll(".bench-fill");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var benchObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            en.target.classList.add("is-animated");
            benchObs.unobserve(en.target);
          }
        });
      },
      { threshold: 0.4 }
    );
    benchFills.forEach(function (el) { benchObs.observe(el); });
  } else {
    benchFills.forEach(function (el) { el.classList.add("is-animated"); });
  }

  /* ---------- Meteors ---------- */
  var meteorHost = document.querySelector(".meteors");
  if (meteorHost && !reduceMotion) {
    for (var m = 0; m < 12; m++) {
      var el = document.createElement("span");
      el.className = "meteor";
      el.style.left = Math.random() * 100 + "%";
      el.style.animation =
        "meteor-fall " + (3 + Math.random() * 4) + "s linear " + Math.random() * 6 + "s infinite";
      meteorHost.appendChild(el);
    }
  }

  /* ---------- Campo de bytes hexadecimais à deriva (fundo global) ----------
     Em vez da rede-de-pontos genérica: colunas de bytes hex que descem devagar,
     alguns acendendo em verde — lê como memória/dados fluindo, on-theme com
     computação de baixo nível. */
  var pcanvas = document.getElementById("particles");
  if (pcanvas && !reduceMotion) {
    var ctx = pcanvas.getContext("2d");
    var W, H, DPR = Math.min(window.devicePixelRatio, 2);
    var HEX = "0123456789ABCDEF";
    var cols = [];
    var FONT = 13, STEP = 20;

    function randByte() { return HEX[(Math.random() * 16) | 0] + HEX[(Math.random() * 16) | 0]; }

    function resizeP() {
      W = window.innerWidth; H = window.innerHeight;
      pcanvas.width = W * DPR; pcanvas.height = H * DPR;
      pcanvas.style.width = W + "px"; pcanvas.style.height = H + "px";
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.font = FONT + 'px "JetBrains Mono", monospace';

      var n = Math.floor(W / 64); // colunas esparsas (não denso tipo "matrix")
      cols = [];
      for (var i = 0; i < n; i++) {
        cols.push({
          x: 30 + (i / n) * (W - 60) + (Math.random() - 0.5) * 30,
          y: Math.random() * H,
          speed: 0.15 + Math.random() * 0.4,
          len: 4 + ((Math.random() * 6) | 0),
          bytes: [],
          hot: Math.random() < 0.25, // algumas colunas acendem
        });
        for (var j = 0; j < cols[i].len; j++) cols[i].bytes.push(randByte());
      }
    }
    resizeP();
    window.addEventListener("resize", resizeP);

    var frame = 0;
    function drawP() {
      frame++;
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < cols.length; i++) {
        var c = cols[i];
        c.y += c.speed;
        if (c.y - c.len * STEP > H) { c.y = -Math.random() * 60; }
        // troca um byte ocasionalmente (dado "mudando")
        if (frame % 30 === 0 && Math.random() < 0.5) {
          c.bytes[(Math.random() * c.bytes.length) | 0] = randByte();
        }
        for (var j = 0; j < c.bytes.length; j++) {
          var yy = c.y - j * STEP;
          if (yy < -STEP || yy > H + STEP) continue;
          var head = j === 0;
          var alpha = head ? 0.55 : 0.11 * (1 - j / c.bytes.length);
          if (c.hot) ctx.fillStyle = "rgba(50, 240, 140, " + (head ? 0.7 : alpha) + ")";
          else ctx.fillStyle = "rgba(92, 99, 112, " + (head ? 0.4 : alpha) + ")";
          ctx.fillText(c.bytes[j], c.x, yy);
        }
      }
      requestAnimationFrame(drawP);
    }
    drawP();
  }

  /* ---------- Text scramble / decode (nos eyebrows das seções) ----------
     Efeito de "decodificação": embaralha caracteres e resolve pro texto final
     quando o elemento entra na viewport. */
  var GLYPHS = "!<>-_\\/[]{}—=+*^?#01ABCDEF";
  function scrambleTo(el) {
    var finalText = el.getAttribute("data-final") || el.textContent;
    el.setAttribute("data-final", finalText);
    var len = finalText.length;
    var frame = 0, resolveAt = [];
    for (var i = 0; i < len; i++) resolveAt[i] = Math.floor(Math.random() * 18) + 6;
    el.classList.add("scrambling");
    function tick() {
      var out = "";
      var done = 0;
      for (var i = 0; i < len; i++) {
        if (frame >= resolveAt[i]) { out += finalText[i]; done++; }
        else if (finalText[i] === " ") { out += " "; done++; }
        else out += GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      el.textContent = out;
      frame++;
      if (done < len) requestAnimationFrame(tick);
      else el.classList.remove("scrambling");
    }
    tick();
  }
  var scrambleEls = document.querySelectorAll(".section-eyebrow");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var scrObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { scrambleTo(en.target); scrObs.unobserve(en.target); }
      });
    }, { threshold: 0.8 });
    scrambleEls.forEach(function (el) { scrObs.observe(el); });
  }

  /* ---------- Spotlight nos cards (segue o mouse) ---------- */
  var spotCards = document.querySelectorAll(".feature-card, .bento-item, .bench-card");
  spotCards.forEach(function (card) {
    card.addEventListener("mousemove", function (e) {
      var rect = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - rect.left) + "px");
      card.style.setProperty("--my", (e.clientY - rect.top) + "px");
    });
  });

  /* ---------- Botões magnéticos ---------- */
  if (!reduceMotion) {
    document.querySelectorAll(".shimmer-btn").forEach(function (btn) {
      btn.addEventListener("mousemove", function (e) {
        var r = btn.getBoundingClientRect();
        var mx = e.clientX - r.left - r.width / 2;
        var my = e.clientY - r.top - r.height / 2;
        btn.style.transform = "translate(" + mx * 0.25 + "px," + (my * 0.25 - 2) + "px)";
      });
      btn.addEventListener("mouseleave", function () { btn.style.transform = ""; });
    });
  }

  /* ---------- Cursor luminoso ---------- */
  if (!reduceMotion && window.matchMedia("(pointer: fine)").matches) {
    var glow = document.createElement("div");
    glow.className = "cursor-glow";
    glow.style.opacity = "0";
    document.body.appendChild(glow);
    var gx = 0, gy = 0, cx = 0, cy = 0;
    window.addEventListener("mousemove", function (e) {
      gx = e.clientX; gy = e.clientY; glow.style.opacity = "1";
    });
    (function glowLoop() {
      cx += (gx - cx) * 0.12; cy += (gy - cy) * 0.12;
      glow.style.transform = "translate(" + cx + "px," + cy + "px)";
      requestAnimationFrame(glowLoop);
    })();
  }

  /* ---------- Terminal "ao vivo": stream de tokens com tok/s ---------- */
  var termBody = document.getElementById("term-body");
  if (termBody && !reduceMotion) {
    var tpsEl = document.getElementById("term-tps");
    var msEl = document.getElementById("term-ms");
    var RESPONSE =
      "O VTE compila cada kernel HIP em runtime e captura o decode " +
      "inteiro num HIP Graph — por isso o Python encosta em ~89% do " +
      "llama.cpp mesmo dirigindo a GPU por ctypes.";
    var TOKENS = RESPONSE.split(/(\s+)/); // mantém espaços como tokens
    var startTs = 0, emitted = 0;

    function line(html) { var d = document.createElement("div"); d.innerHTML = html; termBody.appendChild(d); return d; }

    function typeCmd(text, done) {
      var host = line('<span class="term-prompt"><span class="caret-dollar">$</span> </span><span class="term-cmd"></span><span class="term-caret"></span>');
      var cmdSpan = host.querySelector(".term-cmd");
      var caret = host.querySelector(".term-caret");
      var i = 0;
      (function step() {
        cmdSpan.textContent += text[i++];
        if (i < text.length) setTimeout(step, 32 + Math.random() * 40);
        else { caret.remove(); setTimeout(done, 420); }
      })();
    }

    function streamTokens() {
      var meta = line('<span class="term-meta">→ carregando granite-4.1:3b-q8_0 · prefill…</span>');
      setTimeout(function () {
        var out = line('<span class="term-out"></span><span class="term-caret"></span>');
        var outSpan = out.querySelector(".term-out");
        var caret = out.querySelector(".term-caret");
        startTs = performance.now();
        var idx = 0;
        (function emit() {
          if (idx >= TOKENS.length) {
            caret.remove();
            setTimeout(restart, 4200);
            return;
          }
          outSpan.textContent += TOKENS[idx++];
          emitted++;
          // ~21.9 ms/tok (número real do Granite) com leve jitter
          var elapsed = (performance.now() - startTs) / 1000;
          var tps = emitted / Math.max(elapsed, 0.001);
          if (tpsEl) tpsEl.textContent = (40 + Math.min(tps, 8)).toFixed(1);
          if (msEl) msEl.textContent = (21.9 + (Math.random() - 0.5) * 1.2).toFixed(1);
          termBody.scrollTop = termBody.scrollHeight;
          setTimeout(emit, 55 + Math.random() * 70);
        })();
      }, 700);
    }

    function restart() {
      termBody.innerHTML = "";
      emitted = 0;
      if (tpsEl) tpsEl.textContent = "0.0";
      typeCmd('vte generate "como o VTE chega perto do llama.cpp?"', streamTokens);
    }

    // só inicia quando entra na viewport
    var termObs = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) {
        termObs.disconnect();
        typeCmd('vte generate "como o VTE chega perto do llama.cpp?"', streamTokens);
      }
    }, { threshold: 0.3 });
    termObs.observe(termBody.closest(".live-terminal") || termBody);
  }

  /* ---------- Nav: destaca link ativo ---------- */
  var navLinks = document.querySelectorAll('nav a[href^="#"]');
  var sections = Array.prototype.map.call(navLinks, function (a) {
    return document.querySelector(a.getAttribute("href"));
  });
  if ("IntersectionObserver" in window) {
    var navObs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            navLinks.forEach(function (a) { a.classList.remove("text-accent-green"); });
            var active = document.querySelector('nav a[href="#' + en.target.id + '"]');
            if (active) active.classList.add("text-accent-green");
          }
        });
      },
      { threshold: 0.5 }
    );
    sections.forEach(function (s) { if (s) navObs.observe(s); });
  }
})();
