/* Schematic hero field. Point data is in hero-dots-data.js. No libraries. */
(function () {
  var canvas = document.querySelector("canvas.hero-dots");
  var data = self.ZUSE_DOTS;
  if (!canvas || !data || !canvas.getContext) return;
  var hero = canvas.closest(".hero");
  if (!hero) return;
  var ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx) return;

  var ASPECT = 1402 / 1122;
  var INTRO = 2300;
  var STAGGER = 480;
  var PAL = {
    1: "rgb(112,108,102)",
    2: "rgb(154,148,140)",
    3: "rgb(178,172,162)",
    4: "rgb(208,202,190)",
    5: "rgb(224,218,206)",
    6: "rgb(230,230,226)",
    7: "rgb(176,46,42)",
    8: "rgb(176,142,58)",
    9: "rgb(72,106,128)",
    10: "rgb(38,58,74)",
    11: "rgb(166,164,158)",
    12: "rgb(84,88,94)",
    13: "rgb(198,202,206)"
  };
  var ALPHA = { 1: 0.5, 2: 0.7, 3: 0.8, 4: 0.9, 5: 0.94, 6: 0.96, 7: 0.9, 8: 0.9, 9: 0.5, 10: 0.28, 11: 0.72, 12: 0.42, 13: 0.75 };
  var RAD = { 1: 0.78, 2: 0.95, 3: 1.08, 4: 1.18, 5: 1.24, 6: 1.42, 7: 1.32, 8: 1.32, 9: 0.72, 10: 0.62, 11: 0.92, 12: 0.74, 13: 1 };

  var reduceQ = matchMedia("(prefers-reduced-motion: reduce)");
  var narrowQ = matchMedia("(max-width: 700px)");
  var fineQ = matchMedia("(hover: hover) and (pointer: fine)");
  var reduce = reduceQ.matches;
  var fine = fineQ.matches;

  var nx, ny, col, sx, sy, ph, buckets, n;
  var cw = 1, ch = 1, ox = 0, oy = 0, dw = 1, dh = 1, baseR = 1.3;
  var elapsed = 0, last = 0, raf = 0, acc = 0;
  var onScreen = true, pageOn = document.visibilityState !== "hidden";
  var tx = 0, ty = 0, mx = 0, my = 0, ptr = 0, hasPtr = false;

  function hash(i) {
    var x = Math.imul(i + 1, 374761393);
    x = Math.imul(x ^ (x >>> 13), 1274126177);
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
  }

  function decode(b64) {
    var bin = atob(b64);
    var count = (bin.length / 3) | 0;
    nx = new Float32Array(count);
    ny = new Float32Array(count);
    sx = new Float32Array(count);
    sy = new Float32Array(count);
    ph = new Float32Array(count);
    col = new Uint8Array(count);
    buckets = [];
    for (var c = 0; c < 16; c++) buckets.push([]);
    for (var i = 0, o = 0; i < count; i++, o += 3) {
      var b0 = bin.charCodeAt(o);
      var b1 = bin.charCodeAt(o + 1);
      var b2 = bin.charCodeAt(o + 2);
      nx[i] = (((b0 << 2) | (b1 >> 6)) & 1023) / 1023;
      ny[i] = ((((b1 & 63) << 4) | (b2 >> 4)) & 1023) / 1023;
      col[i] = b2 & 15;
      sx[i] = hash(i * 2) * 1.12 - 0.06;
      sy[i] = hash(i * 2 + 1) * 1.12 - 0.06;
      ph[i] = hash(i + 91) * 6.2831853;
      if (PAL[col[i]]) buckets[col[i]].push(i);
    }
    n = count;
  }

  function heroBox() {
    return hero.getBoundingClientRect();
  }

  function place() {
    var mobile = narrowQ.matches;
    baseR = mobile ? 1.35 : 1.55;
    if (mobile) {
      // The headline stays at the top and the ticker at the bottom.
      // Park the head in the open band between them, not behind the type.
      var box = heroBox();
      var textBottom = 0;
      var nodes = hero.querySelectorAll(":scope > p, :scope > h1, :scope > h2");
      for (var i = 0; i < nodes.length; i++) {
        textBottom = Math.max(textBottom, nodes[i].getBoundingClientRect().bottom - box.top);
      }
      var band = hero.querySelector(".band");
      var bandTop = ch - 36;
      if (band) bandTop = band.getBoundingClientRect().top - box.top;
      var top = textBottom + 10;
      var bot = Math.max(top + 96, bandTop - 8);
      var room = bot - top;
      var natural = (cw * 1.04) / ASPECT;
      dh = Math.max(natural, Math.min(room * 0.98, (cw * 1.16) / ASPECT));
      dw = dh * ASPECT;
      if (dw > cw * 1.14) {
        dw = cw * 1.14;
        dh = dw / ASPECT;
      }
      ox = (cw - dw) / 2;
      var mid = (top + bot) / 2;
      oy = mid - 0.40 * dh;
      var hair = oy + 0.07 * dh;
      if (hair < textBottom + 6) oy += textBottom + 6 - hair;
      baseR = Math.max(1.25, Math.min(2.05, dw / 255));
      return;
    }
    // Whole picture inside the hero, top-aligned, so the head is not cropped.
    dh = ch * 0.98;
    dw = dh * ASPECT;
    if (dw > cw) {
      dw = cw;
      dh = dw / ASPECT;
    }
    ox = (cw - dw) / 2;
    oy = ch * 0.015;
  }

  function ease(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function draw(ms) {
    ctx.clearRect(0, 0, cw, ch);
    var allowMove = !reduce;
    var breathe = allowMove && ms > INTRO + STAGGER - 200;
    var t = ms * 0.001;
    if (fine && allowMove && ms > 1700) {
      if (hasPtr) {
        mx += (tx - mx) * 0.22;
        my += (ty - my) * 0.22;
        ptr += (1 - ptr) * 0.12;
      } else {
        ptr += (0 - ptr) * 0.1;
      }
    } else {
      ptr = 0;
    }
    var reach = 86;
    var reach2 = reach * reach;
    for (var c = 1; c < 16; c++) {
      var bucket = buckets[c];
      if (!bucket || !bucket.length || !PAL[c]) continue;
      var growBase = RAD[c] * baseR;
      ctx.beginPath();
      ctx.fillStyle = PAL[c];
      ctx.globalAlpha = ALPHA[c];
      for (var k = 0; k < bucket.length; k++) {
        var i = bucket[k];
        var delay = (hash(i + 3) * STAGGER);
        var p = reduce ? 1 : ms <= delay ? 0 : ms >= delay + INTRO ? 1 : ease((ms - delay) / INTRO);
        var x = ox + nx[i] * dw;
        var y = oy + ny[i] * dh;
        if (p < 1) {
          x = sx[i] * cw + (x - sx[i] * cw) * p;
          y = sy[i] * ch + (y - sy[i] * ch) * p;
        } else if (breathe) {
          x += Math.sin(t * 0.62 + ph[i]) * 0.7;
          y += Math.cos(t * 0.47 + ph[i]) * 0.5;
        }
        if (ptr > 0.02) {
          var dx = x - mx;
          var dy = y - my;
          var d2 = dx * dx + dy * dy;
          if (d2 < reach2 && d2 > 0.01) {
            var d = Math.sqrt(d2);
            var push = (1 - d / reach) * (1 - d / reach) * 13 * ptr;
            x += (dx / d) * push;
            y += (dy / d) * push;
          }
        }
        var rad = growBase * (0.55 + 0.45 * p);
        if (breathe) rad *= 1 + Math.sin(t * 0.8 + ph[i]) * 0.06;
        ctx.moveTo(x + rad, y);
        ctx.arc(x, y, rad, 0, 6.2831853);
      }
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function resize() {
    var rect = hero.getBoundingClientRect();
    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    cw = Math.max(1, rect.width);
    ch = Math.max(1, rect.height);
    var bw = Math.round(cw * dpr);
    var bh = Math.round(ch * dpr);
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw;
      canvas.height = bh;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    place();
    if (reduce) draw(1e9);
    else if (!raf) draw(elapsed);
  }

  function running() {
    return !reduce && onScreen && pageOn;
  }

  function frame(now) {
    raf = 0;
    if (!running()) return;
    if (!last) last = now;
    var dt = now - last;
    if (dt > 80) dt = 80;
    if (dt < 0) dt = 0;
    last = now;
    elapsed += dt;
    var intro = elapsed < INTRO + STAGGER;
    acc += dt;
    if (intro || acc >= 32) {
      acc = 0;
      draw(elapsed);
    }
    raf = requestAnimationFrame(frame);
  }

  function kick() {
    if (raf || !running()) return;
    last = 0;
    raf = requestAnimationFrame(frame);
  }

  function halt() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    last = 0;
  }

  decode(narrowQ.matches ? data.m : data.d);
  resize();
  kick();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(resize);
  window.addEventListener("load", resize);

  if (window.ResizeObserver) new ResizeObserver(resize).observe(hero);
  window.addEventListener("resize", resize);

  document.addEventListener("visibilitychange", function () {
    pageOn = document.visibilityState === "visible";
    if (pageOn) kick();
    else halt();
  });

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      var en = entries[entries.length - 1];
      onScreen = !!(en && en.isIntersecting);
      if (onScreen) kick();
      else halt();
    }, { threshold: 0 });
    io.observe(hero);
  }

  if (fine) {
    hero.addEventListener("pointermove", function (e) {
      var r = canvas.getBoundingClientRect();
      tx = e.clientX - r.left;
      ty = e.clientY - r.top;
      if (!hasPtr) {
        mx = tx;
        my = ty;
      }
      hasPtr = true;
    }, { passive: true });
    hero.addEventListener("pointerleave", function () {
      hasPtr = false;
    });
  }

  narrowQ.addEventListener("change", function () {
    decode(narrowQ.matches ? data.m : data.d);
    resize();
    if (reduce) draw(1e9);
  });
  reduceQ.addEventListener("change", function () {
    reduce = reduceQ.matches;
    if (reduce) {
      halt();
      draw(1e9);
    } else {
      elapsed = INTRO + STAGGER;
      draw(elapsed);
      kick();
    }
  });
})();
