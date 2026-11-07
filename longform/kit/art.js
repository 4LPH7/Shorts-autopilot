/* Explainer scenes: the drawing the LLM made for the scene (S.art, cleaned by explainer.py) in the room layer, brought to
   life on the paused timeline. Moving parts carry a class (bob, drift, swim, sway, spin, pulse, blink); a part with
   data-beat="N" appears when the scene's Nth line starts. Only tweens on tl: nothing runs on its own clock, so every
   frame the renderer seeks to is exact. */
(function (g) {
  const MOVES = {
    bob: (i) => [{ y: 0 }, { y: -16, duration: 1.8 + (i % 3) * 0.35 }],
    drift: (i) => [{ x: -14 }, { x: 14, duration: 3.2 + (i % 3) * 0.6 }],
    swim: (i) => [{ x: -30, rotation: -2 }, { x: 30, rotation: 2, duration: 2.6 + (i % 3) * 0.5 }],
    sway: (i) => [{ rotation: -4 }, { rotation: 4, duration: 1.6 + (i % 3) * 0.3 }],
    pulse: (i) => [{ scale: 1 }, { scale: 1.06, duration: 1.3 + (i % 3) * 0.2 }],
  };
  function mount(tl, host, S) {
    host.innerHTML = S.art || '';
    const svg = host.querySelector('svg');
    if (!svg) return;
    let i = 0;
    for (const [cls, mv] of Object.entries(MOVES)) {
      svg.querySelectorAll('.' + cls).forEach((n) => {
        const [from, to] = mv(i++);
        tl.set(n, { transformOrigin: cls === 'sway' ? '50% 100%' : '50% 50%' }, 0);
        tl.fromTo(n, from, { ...to, ease: 'sine.inOut', yoyo: true, repeat: Math.ceil(S.dur / to.duration) + 1 }, 0);
      });
    }
    svg.querySelectorAll('.spin').forEach((n) => {
      tl.set(n, { transformOrigin: '50% 50%' }, 0);
      tl.fromTo(n, { rotation: 0 }, { rotation: 15 * S.dur, duration: S.dur, ease: 'none' }, 0);
    });
    svg.querySelectorAll('.blink').forEach((n, k) => {
      tl.set(n, { transformOrigin: '50% 50%' }, 0);
      for (let t = 1.2 + k * 0.4; t < S.dur - 0.3; t += 3.4) {
        tl.to(n, { scaleY: 0.1, duration: 0.08 }, t);
        tl.to(n, { scaleY: 1, duration: 0.1 }, t + 0.1);
      }
    });
    svg.querySelectorAll('[data-beat]').forEach((n) => {
      const line = (S.lines || [])[(parseInt(n.getAttribute('data-beat'), 10) || 1) - 1];
      if (!line || line.t < 0.3) return;
      tl.set(n, { opacity: 0 }, 0);
      tl.to(n, { opacity: 1, duration: 0.5, ease: 'power2.out' }, line.t);
    });
  }
  g.Art = { mount };
})(typeof window !== 'undefined' ? window : globalThis);
