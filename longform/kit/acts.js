/* What a puppet can do. Acts.char(tl, id, look, cfg) returns a handle whose methods add tweens to the scene's paused
   GSAP timeline at absolute times. Nothing random except seeded schedules; every pose is a function of time.
   Motions that can overlap never share a property, so any frame renders the same however the timeline is sought:
   head rotation = where they look and their attitude; nod (inside the head) = speech accents, nods, head shakes;
   body rotation = the idle weight shift; body y = walking, hopping, sitting. Tweens that may overlap use fromTo. */
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
  // lip sync (lf_voice.py): A M/B/P closed, B teeth, C open, D wide, E round, F pucker, G F/V, H L/TH, X the mood's own rest
  const SHAPE = { A: 'mc0', B: 'mB', C: 'mC', D: 'm2', E: 'm3', F: 'mF', G: 'mG', H: 'mH' };
  const OLD = [null, 'm1', 'm2', 'm3'];        // films voiced before lip sync: loudness 0 closed, 1 small, 2 wide, 3 round
  const MOUTHS = ['mc0', 'mc1', 'mc2', 'm1', 'm2', 'm3', 'mB', 'mC', 'mF', 'mG', 'mH'];
  const CLOSED = ['mc0', 'mc1', 'mc2'];
  const rng = (seed) => () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const hash = (s) => [...s].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) | 0, 7);
  const reps = (span, step) => { const r = Math.max(1, Math.floor(span / step) - 1); return r % 2 ? r : Math.max(1, r - 1); }; // odd: a yoyo ends where it began

  function char(tl, id, look, cfg) {
    const P = g.Rig.parts(id);
    const s = look.h || 1;
    const c = { id, P, x: cfg.x, y: cfg.y, face: cfg.face || 1, scale: s, emoName: 'neutral', seated: false, inBed: false, floor: cfg.y, closed: 0, lines: 0, r: rng(hash(id)) };
    g.gsap.set(P.head, { scale: look.hs || 1 });
    g.gsap.set(P.browL, { svgOrigin: '-14.5 -308' });
    g.gsap.set(P.browR, { svgOrigin: '14.5 -308' });
    tl.set(P.root, { x: c.x, y: c.y, scaleX: c.face * s, scaleY: s }, 0);
    tl.set([P.armL, P.armR, P.foreL, P.foreR], { rotation: (i) => [REST.armL, REST.armR, REST.foreL, REST.foreR][i] }, 0);
    const mouths = MOUTHS.map((n) => P[n]);
    const show = (t, name) => tl.set(mouths, { opacity: (i) => (MOUTHS[i] === name ? 1 : 0) }, t);
    const rest = () => CLOSED[c.closed];

    c.emo = (t, name) => {
      const e = EMO[name] || EMO.neutral;
      c.emoName = name; c.closed = e.mc;
      tl.to(P.browL, { rotation: e.bl[0], y: e.bl[1], duration: 0.18, ease: 'power2.out' }, t);
      tl.to(P.browR, { rotation: e.br[0], y: e.br[1], duration: 0.18, ease: 'power2.out' }, t);
      tl.to([P.eyeL, P.eyeR], { scaleY: e.eye, scaleX: e.eye > 1 ? e.eye * 0.95 : 1, duration: 0.14, ease: 'power2.out' }, t);
      show(t, rest());
    };
    // runs: [[dt, shape]] lip sync, or [[dt, 0-3]] from older films; accents: [dt] strong words; busy(t): the nod layer is taken
    c.say = (t, d, runs, accents, busy) => {
      for (const [dt, st] of runs) show(t + dt, (typeof st === 'number' ? OLD[st] : SHAPE[st]) || rest());
      show(t + d, rest());
      const tilt = ++c.lines % 2 ? 2.2 : -1.8;               // one gentle attitude per line, back to level when it ends
      tl.to(P.head, { rotation: tilt, duration: 0.45, ease: 'sine.inOut' }, t);
      tl.to(P.head, { rotation: 0, duration: 0.3, ease: 'sine.inOut' }, t + d);
      (accents || []).forEach((a, k) => {
        if (busy && busy(t + a)) return;
        tl.fromTo(P.nod, { rotation: 0, y: 0 }, { rotation: k % 3 === 2 ? -2 : 2.8, y: 2.4, duration: 0.15, ease: 'power2.out', yoyo: true, repeat: 1 }, Math.max(0, t + a - 0.05));
      });
    };
    c.ack = (t) => tl.fromTo(P.nod, { rotation: 0, y: 0 }, { rotation: 4.5, y: 3, duration: 0.2, ease: 'sine.inOut', yoyo: true, repeat: 1 }, t);
    c.look = (t, dx, dy = 0, d = 0.2) => {
      tl.to([P.pupL, P.pupR], { x: dx, y: dy, duration: d, ease: 'power2.out' }, t);
      tl.to(P.head, { rotation: dx * 0.35, duration: d + 0.1, ease: 'sine.out' }, t);
    };
    c.pose = (t, name, d = 1.2) => { // upper arms overshoot a little, forearms follow a beat later; d ends before the next arm move
      const q = POSE[name]; if (!q) return;
      tl.to([P.armL, P.armR], { rotation: (i) => [q[0], q[2]][i], duration: 0.32, ease: 'back.out(1.6)' }, t);
      tl.to([P.foreL, P.foreR], { rotation: (i) => [q[1], q[3]][i], duration: 0.3, ease: 'back.out(2)' }, t + 0.05);
      if (name === 'wave') tl.to(P.foreR, { rotation: 22, duration: 0.2, yoyo: true, repeat: reps(d - 0.45, 0.2), ease: 'sine.inOut' }, t + 0.36);
      if (name === 'shrug') { tl.to(P.torso, { y: -7, duration: 0.2, ease: 'power2.out' }, t); tl.to(P.head, { rotation: 6, duration: 0.25 }, t); tl.to([P.torso, P.head], { y: 0, rotation: 0, duration: 0.3 }, t + d - 0.3); }
      if (name === 'clap') tl.to([P.armL, P.armR, P.foreL, P.foreR], { rotation: (i) => [-26, 26, -60, 60][i], duration: 0.12, yoyo: true, repeat: reps(d - 0.45, 0.12) }, t + 0.38);
      tl.to([P.armL, P.armR], { rotation: (i) => [REST.armL, REST.armR][i], duration: 0.4, ease: 'power2.inOut' }, t + d);
      tl.to([P.foreL, P.foreR], { rotation: (i) => [REST.foreL, REST.foreR][i], duration: 0.4, ease: 'power2.inOut' }, t + d + 0.06);
    };
    c.walk = (t, d, toX, face) => { // face: which way to stand once there (toward the nearest person)
      const dir = toX >= c.x ? 1 : -1, n = Math.max(2, Math.round(d / 0.28));
      tl.set(P.root, { scaleX: dir * s }, t);
      tl.to(P.root, { x: toX, duration: d, ease: 'power1.inOut' }, t);
      tl.fromTo(P.legL, { rotation: 20 }, { rotation: -20, duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo(P.legR, { rotation: -20 }, { rotation: 20, duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo([P.armL, P.armR], { rotation: (i) => (i ? 18 : -18) }, { rotation: (i) => (i ? -18 : 18), duration: 0.28, yoyo: true, repeat: n - 1, ease: 'sine.inOut' }, t);
      tl.fromTo(P.body, { y: 0 }, { y: -7, duration: 0.14, yoyo: true, repeat: n * 2 - 1, ease: 'sine.out' }, t);
      tl.to([P.legL, P.legR], { rotation: 0, duration: 0.2 }, t + d);
      tl.to([P.armL, P.armR], { rotation: (i) => REST[i ? 'armR' : 'armL'], duration: 0.2 }, t + d);
      c.face = face || c.face;
      tl.set(P.root, { scaleX: c.face * s }, t + d + 0.2);
      c.x = toX;
    };
    c.hop = (t, h = 46) => {
      tl.to(P.body, { scaleY: 0.92, duration: 0.09, ease: 'power2.in' }, t);
      tl.to(P.body, { scaleY: 1.04, y: -h, duration: 0.2, ease: 'power2.out' }, t + 0.09);
      tl.to(P.body, { scaleY: 0.95, y: 0, duration: 0.2, ease: 'power2.in' }, t + 0.3);
      tl.to(P.body, { scaleY: 1, duration: 0.12, ease: 'back.out(3)' }, t + 0.5);
    };
    c.shake = (t, d, amt = 3) => tl.fromTo(P.body, { y: 0 }, { y: -amt, duration: 0.09, yoyo: true, repeat: reps(d, 0.09) }, t);
    c.nod = (t) => tl.fromTo(P.nod, { rotation: 0, y: 0 }, { rotation: 7, y: 4, duration: 0.16, yoyo: true, repeat: 3, ease: 'sine.inOut' }, t);
    c.no = (t) => tl.fromTo(P.nod, { x: 0 }, { x: 5, duration: 0.14, yoyo: true, repeat: 3, ease: 'sine.inOut' }, t);
    c.sit = (t, d = 0.3) => { tl.to(P.body, { y: 58, duration: d, ease: 'power2.inOut' }, t); tl.to([P.legL, P.legR], { scaleY: 0.52, duration: d }, t); tl.to(P.chair, { opacity: 1, duration: d * 0.6 }, t); c.seated = true; };
    c.stand = (t, d = 0.3, toX) => {
      if (c.inBed) return c.getUp(t, toX ?? c.x + 240 * c.face);
      tl.to(P.body, { y: 0, duration: d, ease: 'power2.inOut' }, t); tl.to([P.legL, P.legR], { scaleY: 1, duration: d }, t); tl.to(P.chair, { opacity: 0, duration: d * 0.6 }, t); c.seated = false;
    };
    c.bed = (color, floor) => { // sitting up in bed under the room's blanket from the first frame; the legs are under it
      P.blanket.setAttribute('fill', color);
      tl.set([P.legL, P.legR, P.shadow], { opacity: 0 }, 0);
      tl.set(P.blanket, { opacity: 1 }, 0);
      c.inBed = true; c.floor = floor;
    };
    c.getUp = (t, toX) => {
      tl.to(P.blanket, { opacity: 0, duration: 0.25 }, t);
      tl.to([P.legL, P.legR, P.shadow], { opacity: 1, duration: 0.25 }, t + 0.1);
      tl.to(P.root, { x: toX, y: c.floor, duration: 0.6, ease: 'power2.inOut' }, t);
      c.x = toX; c.y = c.floor; c.inBed = false;
    };
    c.move = (t, x, y, d = 0.5) => { tl.to(P.root, { x, y, duration: d, ease: 'power2.inOut' }, t); c.x = x; if (y !== undefined) c.y = y; };
    c.flip = (t, face) => { tl.set(P.root, { scaleX: face * s }, t); c.face = face; };
    c.alive = (t0, t1) => { // breathing, blinks and a slow weight shift for the stretch [t0, t1]
      tl.to(P.torso, { scaleY: 1.016, duration: 1.4, yoyo: true, repeat: Math.max(1, Math.ceil((t1 - t0) / 1.4)), ease: 'sine.inOut' }, t0);
      for (let at = t0 + 1 + c.r() * 2.5; at < t1 - 0.3; at += 2.8 + c.r() * 2.4) tl.to([P.eyeL, P.eyeR], { scaleY: 0.08, duration: 0.07, yoyo: true, repeat: 1 }, at);
      const sway = 2.6 + c.r() * 1.4;
      tl.fromTo(P.body, { rotation: -0.6 }, { rotation: 0.6, duration: sway, yoyo: true, repeat: Math.max(1, Math.ceil((t1 - t0) / sway)), ease: 'sine.inOut' }, t0);
    };
    show(0, 'mc0');
    return c;
  }
  g.Acts = { EMO, POSE, SHAPE, char, rng, hash };
})(typeof window !== 'undefined' ? window : globalThis);
