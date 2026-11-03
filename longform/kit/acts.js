/* What a puppet can do. Acts.char(tl, id, look, cfg) returns a handle whose methods add tweens to the scene's paused
   GSAP timeline at absolute times. Nothing random except the seeded blink schedule; every pose is a function of time. */
(function (g) {
  const EMO = { // brow rotation/lift per side, which closed mouth (0 flat, 1 smile, 2 frown), eye size
    neutral: { bl: [0, 0], br: [0, 0], mc: 0, eye: 1 }, happy: { bl: [-5, -3], br: [5, -3], mc: 1, eye: 1 },
    sad: { bl: [14, 0], br: [-14, 0], mc: 2, eye: 0.95 }, angry: { bl: [-17, 2], br: [17, 2], mc: 2, eye: 0.9 },
    surprised: { bl: [-4, -9], br: [4, -9], mc: 0, eye: 1.2 }, scared: { bl: [12, -7], br: [-12, -7], mc: 2, eye: 1.18 },
    thinking: { bl: [-8, -7], br: [4, 1], mc: 0, eye: 1 }, sleep: { bl: [8, 3], br: [-8, 3], mc: 0, eye: 0.08 },
  };
  const REST = { armL: 5, armR: -5, foreL: 4, foreR: -4 };
  const POSE = { // [armL, foreL, armR, foreR] rotations (armL outward is +, armR outward is -)
    open: [28, 18, -28, -18], point: [5, 4, -78, -8], shrug: [30, 40, -30, -40], think: [5, 4, -150, 70], wave: [5, 4, -145, -20],
    up: [155, 10, -155, -10], hold: [5, 4, -42, -62], clap: [-34, -70, 34, 70], hug: [-38, -88, 38, 88], fist: [20, 100, -20, -100],
  };
  const rng = (seed) => () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const hash = (s) => [...s].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) | 0, 7);

  function char(tl, id, look, cfg) {
    const P = g.Rig.parts(id), G = g.gsap;
    const s = look.h || 1;
    const c = { id, P, x: cfg.x, y: cfg.y, face: cfg.face || 1, scale: s, emoName: 'neutral', seated: false, r: rng(hash(id)) };
    G.set(P.head, { scale: look.hs || 1 });
    G.set(P.browL, { svgOrigin: '-14.5 -308' });
    G.set(P.browR, { svgOrigin: '14.5 -308' });
    tl.set(P.root, { x: c.x, y: c.y, scaleX: c.face * s, scaleY: s }, 0);
    tl.set([P.armL, P.armR, P.foreL, P.foreR], { rotation: (i) => [REST.armL, REST.armR, REST.foreL, REST.foreR][i] }, 0);
    const open = [P.mc0, P.mc1, P.mc2, P.m1, P.m2, P.m3];
    const show = (t, k) => tl.set(open, { opacity: (i) => (i === k ? 1 : 0) }, t);

    c.emo = (t, name) => {
      const e = EMO[name] || EMO.neutral;
      c.emoName = name; c.closed = e.mc;
      tl.to(P.browL, { rotation: e.bl[0], y: e.bl[1], duration: 0.18, ease: 'power2.out' }, t);
      tl.to(P.browR, { rotation: e.br[0], y: e.br[1], duration: 0.18, ease: 'power2.out' }, t);
      tl.to([P.eyeL, P.eyeR], { scaleY: e.eye, scaleX: e.eye > 1 ? e.eye * 0.95 : 1, duration: 0.14, ease: 'power2.out' }, t);
      show(t, e.mc);
    };
    c.closed = 0;
    c.say = (t, d, runs) => { // runs: [[dt, state 0-3]] from the audio envelope
      for (const [dt, st] of runs) show(t + dt, st === 0 ? c.closed : 2 + st);
      show(t + d, c.closed);
      for (let k = 0, at = t + 0.08; at < t + d - 0.2; k++, at += 0.5 + c.r() * 0.18) {
        const a = [2.4, -1.8, 1.2, -2.2][k % 4];
        tl.to(P.head, { rotation: a, y: k % 2 ? 1.5 : -1.5, duration: 0.3, ease: 'sine.inOut' }, at);
      }
      tl.to(P.head, { rotation: 0, y: 0, duration: 0.3, ease: 'sine.out' }, t + d);
    };
    c.look = (t, dx, dy = 0, d = 0.2) => {
      tl.to([P.pupL, P.pupR], { x: dx, y: dy, duration: d, ease: 'power2.out' }, t);
      tl.to(P.head, { rotation: dx * 0.35, duration: d + 0.1, ease: 'sine.out' }, t);
    };
    c.pose = (t, name, d = 1.2) => {
      const q = POSE[name]; if (!q) return;
      const to = { duration: 0.28, ease: 'power2.out' };
      tl.to([P.armL, P.foreL, P.armR, P.foreR], { ...to, rotation: (i) => q[i] }, t);
      if (name === 'wave') tl.to(P.foreR, { rotation: 22, duration: 0.2, yoyo: true, repeat: Math.max(1, Math.round(d / 0.2) | 1), ease: 'sine.inOut' }, t + 0.3);
      if (name === 'shrug') { tl.to(P.torso, { y: -7, duration: 0.2, ease: 'power2.out' }, t); tl.to(P.head, { rotation: 6, duration: 0.25 }, t); tl.to([P.torso, P.head], { y: 0, rotation: 0, duration: 0.3 }, t + d - 0.3); }
      if (name === 'clap') tl.to([P.armL, P.armR, P.foreL, P.foreR], { rotation: (i) => [-26, 26, -60, 60][i], duration: 0.12, yoyo: true, repeat: Math.max(1, Math.round(d / 0.12) | 1) }, t + 0.3);
      tl.to([P.armL, P.foreL, P.armR, P.foreR], { ...to, rotation: (i) => [REST.armL, REST.foreL, REST.armR, REST.foreR][i] }, t + d);
    };
    c.walk = (t, d, toX) => {
      const dir = toX >= c.x ? 1 : -1, n = Math.max(2, Math.round(d / 0.28));
      tl.set(P.root, { scaleX: dir * s }, t);
      tl.to(P.root, { x: toX, duration: d, ease: 'power1.inOut' }, t);
      tl.fromTo(P.legL, { rotation: 20 }, { rotation: -20, duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo(P.legR, { rotation: -20 }, { rotation: 20, duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo([P.armL, P.armR], { rotation: (i) => (i ? 18 : -18) }, { rotation: (i) => (i ? -18 : 18), duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo(P.body, { y: 0 }, { y: -7, duration: 0.14, yoyo: true, repeat: n * 2 - 1, ease: 'sine.out' }, t);
      tl.to([P.legL, P.legR], { rotation: 0, duration: 0.2 }, t + d);
      tl.to([P.armL, P.armR], { rotation: (i) => REST[i ? 'armR' : 'armL'], duration: 0.2 }, t + d);
      tl.set(P.root, { scaleX: c.face * s }, t + d + 0.25);
      c.x = toX;
    };
    c.hop = (t, h = 46) => {
      tl.to(P.body, { scaleY: 0.92, duration: 0.09, ease: 'power2.in' }, t);
      tl.to(P.body, { scaleY: 1.04, y: -h, duration: 0.2, ease: 'power2.out' }, t + 0.09);
      tl.to(P.body, { scaleY: 0.95, y: 0, duration: 0.2, ease: 'power2.in' }, t + 0.3);
      tl.to(P.body, { scaleY: 1, duration: 0.12, ease: 'back.out(3)' }, t + 0.5);
    };
    c.shake = (t, d, amt = 3) => tl.to(P.body, { y: -amt, duration: 0.09, yoyo: true, repeat: Math.max(1, Math.round(d / 0.09) | 1) }, t);
    c.nod = (t) => tl.to(P.head, { rotation: 7, y: 4, duration: 0.16, yoyo: true, repeat: 3, ease: 'sine.inOut' }, t);
    c.no = (t) => tl.to(P.head, { x: 5, duration: 0.14, yoyo: true, repeat: 3, ease: 'sine.inOut' }, t);
    c.sit = (t, d = 0.3) => { tl.to(P.body, { y: 58, duration: d, ease: 'power2.inOut' }, t); tl.to([P.legL, P.legR], { scaleY: 0.52, duration: d }, t); tl.to(P.chair, { opacity: 1, duration: d * 0.6 }, t); c.seated = true; };
    c.stand = (t, d = 0.3) => { tl.to(P.body, { y: 0, duration: d, ease: 'power2.inOut' }, t); tl.to([P.legL, P.legR], { scaleY: 1, duration: d }, t); tl.to(P.chair, { opacity: 0, duration: d * 0.6 }, t); c.seated = false; };
    c.lie = (t, at, d = 0.4) => { // flat on a bed, head to the right (the pillow side of the bed drawings)
      tl.to(P.root, { x: at.x - 286 * s, y: at.y, rotation: 90, duration: d, ease: 'power2.inOut' }, t);
    };
    c.move = (t, x, y, d = 0.5) => { tl.to(P.root, { x, y, duration: d, ease: 'power2.inOut' }, t); c.x = x; if (y !== undefined) c.y = y; };
    c.flip = (t, face) => { tl.set(P.root, { scaleX: face * s }, t); c.face = face; };
    c.alive = (t0, t1) => { // breathing and blinks for the stretch [t0, t1]
      tl.to(P.torso, { scaleY: 1.016, duration: 1.4, yoyo: true, repeat: Math.max(1, Math.ceil((t1 - t0) / 1.4)), ease: 'sine.inOut' }, t0);
      for (let at = t0 + 1 + c.r() * 2.5; at < t1 - 0.3; at += 2.8 + c.r() * 2.4) tl.to([P.eyeL, P.eyeR], { scaleY: 0.08, duration: 0.07, yoyo: true, repeat: 1 }, at);
    };
    show(0, 0);
    return c;
  }
  g.Acts = { EMO, POSE, char, rng, hash };
})(typeof window !== 'undefined' ? window : globalThis);
