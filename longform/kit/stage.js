/* Builds one scene on its paused GSAP timeline from the scene description the builder (lf_build.py) writes.
   Skeleton elements (#<pre>-cam, -room, -chars, -cards, -cap, -cover) are in the scene's HTML; this fills them. */
(function (g) {
  const WORLD = [1920, 1080];
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function build(tl, S, pre) {
    const $ = (n) => document.getElementById(`${pre}-${n}`);
    const cam = $('cam'), cards = $('cards'), caps = $('cap'), cover = $('cover');
    const [W, H] = S.world || WORLD;          // an explainer's drawing is drawn at the frame's own size
    if (S.art) g.Art.mount(tl, $('room'), S);   // an explainer: the LLM's drawing instead of a room
    else {
      $('room').innerHTML = g.Rooms.make(S.room.kind, S.room.tone, pre).svg;
      if (S.bg) $('room').style.opacity = 0;   // a generated background stands in for the flat room
    }
    const order = [...S.cast].sort((a, b) => a.y - b.y);
    $('chars').innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${order.map((c) => g.Rig.svg(`${pre}-${c.id}`, c.look)).join('')}</svg>`;
    const mid = S.cast.reduce((a, c) => a + c.x, 0) / S.cast.length;
    const ch = {};
    for (const c of S.cast) {
      const h = (ch[c.id] = g.Acts.char(tl, `${pre}-${c.id}`, c.look, { x: c.x, y: c.y, face: c.face || (c.x > mid ? -1 : 1) }));
      h.emo(0, c.mood || 'neutral');
      if (c.start === 'bed' && c.bed) h.bed(c.bed, c.floor || 944);
      else if (c.start === 'sit' || c.start === 'lie') h.sit(0, 0);   // 'lie' is from plans made before beds: nobody floats sideways
      h.alive(0, S.dur);
    }
    // per character: when the arms are next needed (a pose ends before then) and when the nod layer is taken
    const armAt = {}, nodAt = {};
    for (const e of S.events) {
      if (e.who && ['pose', 'walk', 'stand'].includes(e.do)) (armAt[e.who] ||= []).push(e.t);
      if (e.who && ['nod', 'no'].includes(e.do)) (nodAt[e.who] ||= []).push(e.t);
    }
    const nextArm = (who, t) => Math.min(Infinity, ...(armAt[who] || []).filter((x) => x > t + 1e-6));
    const nodBusy = (who) => (t) => (nodAt[who] || []).some((x) => t > x - 0.4 && t < x + 0.8);
    // camera: wide unless a shot says otherwise; a slow push after every move. The world is always 1920x1080; the frame
    // (S.frame, a Short's 1080x1920) is the window onto it, never zoomed out past filling it.
    const [VW, VH] = S.frame || [W, H], tall = VH > VW, kmin = Math.max(VW / W, VH / H);
    // (fx, fy) of the world lands at (VW / 2, VH * ay) of the frame, as near as the room's edges allow
    const fit = (fx, fy, k, ay) => ({ fx, fy, k, ay, x: clamp(VW / 2 - fx * k, VW - W * k, 0), y: clamp(VH * ay - fy * k, VH - H * k, 0) });
    const view = (mode, on) => {
      const pts = [].concat(on || []).map((id) => ch[id]).filter(Boolean);
      if (!S.cast.length) {                        // nobody on screen (an explainer): wide shows the whole drawing, mid and close push in on its focus
        const [fx, fy] = S.focus || [W / 2, H / 2];
        return mode === 'mid' || mode === 'close' ? fit(fx, fy, kmin * (mode === 'close' ? 1.8 : 1.35), 0.5) : fit(W / 2, H / 2, kmin, 0.5);
      }
      if (tall) {                                  // vertical: the cast's middle in a tight wide, feet near the bottom
        const all = Object.values(ch), cx = all.reduce((a, c) => a + c.x, 0) / all.length, p = pts[0];
        if (mode === 'mid' && p) return fit(p.x, p.y - 200 * p.scale, kmin * 1.6, 0.55);
        if (mode === 'close' && p) return fit(p.x, p.y - 285 * p.scale, kmin * 2.3, 0.4);
        if (mode === 'two' && pts.length > 1) return fit((pts[0].x + pts[1].x) / 2, pts[0].y, kmin * 1.25, 0.84);
        return fit(cx, all[0] ? all[0].y : 944, kmin * 1.12, 0.86);
      }
      let fx = 960, fy = 540, k = 1;
      if (mode === 'mid' && pts[0]) { fx = pts[0].x; fy = pts[0].y - 170; k = 1.5; }
      else if (mode === 'close' && pts[0]) { fx = pts[0].x; fy = pts[0].y - 250 * pts[0].scale; k = 2.2; }
      else if (mode === 'two' && pts.length > 1) { fx = (pts[0].x + pts[1].x) / 2; fy = pts[0].y - 190; k = clamp(1500 / (Math.abs(pts[0].x - pts[1].x) + 520), 1.1, 1.8); }
      return fit(fx, fy, k, 0.5);
    };
    const opening = view('wide');                  // where everyone stands at the start, before any walk moves them
    const shots = [{ t: 0, mode: 'wide' }, ...S.events.filter((e) => e.do === 'shot')].sort((a, b) => a.t - b.t);
    tl.set(cam, { x: opening.x, y: opening.y, scale: opening.k, transformOrigin: '0 0' }, 0);
    let cur = { x: opening.x, y: opening.y, k: opening.k };
    const pending = [];
    // events in time order, so each shot sees where its character stands at that moment
    const evs = [...S.events].sort((a, b) => a.t - b.t);
    for (const ev of evs) {
      const c = ch[ev.who];
      if (ev.do === 'shot') pending.push({ t: ev.t, v: view(ev.mode, ev.on), mode: ev.mode });
      else if (ev.do === 'say' && c) {
        if (ev.emo) c.emo(ev.t, ev.emo);
        c.say(ev.t, ev.d, ev.mouth || [], ev.accents, nodBusy(ev.who));
        const others = Object.entries(ch).filter(([, o]) => o !== c);
        for (const [, o] of others) o.look(ev.t, Math.sign(c.x - o.x) * 4, 0, 0.25);
        if (ev.d > 2.4 && others.length) {                     // the nearest listener nods along once
          const [lid, l] = others.reduce((a, b) => (Math.abs(b[1].x - c.x) < Math.abs(a[1].x - c.x) ? b : a));
          const at = ev.t + ev.d * 0.62;
          if (!nodBusy(lid)(at)) l.ack(at);
        }
      } else if (ev.do === 'emo' && c) c.emo(ev.t, ev.emo);
      else if (ev.do === 'pose' && c) {
        const d = Math.min(ev.d || 1.2, nextArm(ev.who, ev.t) - ev.t - 0.45);
        if (d >= 0.5) c.pose(ev.t, ev.pose, d);
      } else if (ev.do === 'walk' && c) c.walk(ev.t, ev.d, ev.to, ev.face);
      else if (ev.do === 'look' && c) c.look(ev.t, ev.dx, ev.dy || 0);
      else if (ev.do === 'card') g.Cards.add(tl, cards, pre, ev);
      else if (c && ['hop', 'nod', 'no'].includes(ev.do)) c[ev.do](ev.t);
      else if (c && ev.do === 'stand') c.stand(ev.t, 0.35, ev.to);
      else if (c && ev.do === 'sit') c.sit(ev.t, 0.35);
      else if (c && ev.do === 'shake') c.shake(ev.t, ev.d || 0.6);
    }
    const seq = [{ t: 0, v: tall ? opening : view('wide') }, ...pending.map((p) => ({ t: p.t, v: p.v }))].sort((a, b) => a.t - b.t);
    seq.forEach((s, i) => {
      const hold = (seq[i + 1] ? seq[i + 1].t : S.dur) - s.t;
      const mv = Math.min(0.65, hold);
      if (i > 0) tl.fromTo(cam, { x: cur.x, y: cur.y, scale: cur.k }, { x: s.v.x, y: s.v.y, scale: s.v.k, duration: mv, ease: 'power3.inOut' }, s.t);
      const end = fit(s.v.fx, s.v.fy, s.v.k * 1.03, s.v.ay);
      if (hold - mv > 0.3) tl.fromTo(cam, { x: s.v.x, y: s.v.y, scale: s.v.k }, { x: end.x, y: end.y, scale: end.k, duration: hold - mv, ease: 'none' }, s.t + mv);
      cur = hold - mv > 0.3 ? end : s.v;
    });
    // captions
    caps.innerHTML = S.caps.map((c, i) => `<div id="${pre}-cp${i}" class="cp"><span>${c.who ? `<b style="color:${c.color || '#ffd166'}">${esc(c.who)}</b> ` : ''}${esc(c.text)}</span></div>`).join('');
    S.caps.forEach((c, i) => { tl.set($(`cp${i}`), { opacity: 1 }, c.t); tl.set($(`cp${i}`), { opacity: 0 }, c.t + c.d); });
    // how the scene meets its neighbours
    const BLACK = '#000', GOLD = '#ffcc33';
    tl.set(cover, { opacity: 0, x: 0 }, 0);
    if (S.cover_in === 'fade') { tl.set(cover, { backgroundColor: BLACK, opacity: 1 }, 0); tl.to(cover, { opacity: 0, duration: 0.45 }, 0); }
    else if (S.cover_in === 'wipe') { tl.set(cover, { backgroundColor: GOLD, opacity: 1 }, 0); tl.to(cover, { x: VW, duration: 0.5, ease: 'power3.inOut' }, 0); }
    if (S.cover_out === 'fade') { tl.set(cover, { backgroundColor: BLACK, opacity: 0, x: 0 }, S.dur - 0.4); tl.to(cover, { opacity: 1, duration: 0.35 }, S.dur - 0.35); }
    else if (S.cover_out === 'wipe') { tl.set(cover, { backgroundColor: GOLD, opacity: 1, x: -VW }, S.dur - 0.42); tl.to(cover, { x: 0, duration: 0.4, ease: 'power3.in' }, S.dur - 0.4); }
    tl.set({}, {}, S.dur);
  }
  g.Stage = { build };
})(typeof window !== 'undefined' ? window : globalThis);
