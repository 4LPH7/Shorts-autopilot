/* Builds one scene on its paused GSAP timeline from the scene description the builder (lf_build.py) writes.
   Skeleton elements (#<pre>-cam, -room, -chars, -cards, -cap, -cover) are in the scene's HTML; this fills them. */
(function (g) {
  const W = 1920, H = 1080;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function build(tl, S, pre) {
    const $ = (n) => document.getElementById(`${pre}-${n}`);
    const cam = $('cam'), cards = $('cards'), caps = $('cap'), cover = $('cover');
    const room = g.Rooms.make(S.room.kind, S.room.tone, pre);
    $('room').innerHTML = room.svg;
    const order = [...S.cast].sort((a, b) => a.y - b.y);
    $('chars').innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${order.map((c) => g.Rig.svg(`${pre}-${c.id}`, c.look)).join('')}</svg>`;
    const mid = S.cast.reduce((a, c) => a + c.x, 0) / S.cast.length;
    const ch = {};
    for (const c of S.cast) {
      const h = (ch[c.id] = g.Acts.char(tl, `${pre}-${c.id}`, c.look, { x: c.x, y: c.y, face: c.face || (c.x > mid ? -1 : 1) }));
      h.emo(0, c.mood || 'neutral');
      if (c.start === 'sit') h.sit(0, 0);
      if (c.start === 'lie') h.lie(0, room.anchors.lie || { x: c.x, y: c.y }, 0);
      h.alive(0, S.dur);
    }
    // camera: wide unless a shot says otherwise; a slow push after every move
    const view = (mode, on) => {
      const pts = [].concat(on || []).map((id) => ch[id]).filter(Boolean);
      let fx = 960, fy = 540, k = 1;
      if (mode === 'mid' && pts[0]) { fx = pts[0].x; fy = pts[0].y - 170; k = 1.5; }
      else if (mode === 'close' && pts[0]) { fx = pts[0].x; fy = pts[0].y - 250 * pts[0].scale; k = 2.2; }
      else if (mode === 'two' && pts.length > 1) { fx = (pts[0].x + pts[1].x) / 2; fy = pts[0].y - 190; k = clamp(1500 / (Math.abs(pts[0].x - pts[1].x) + 520), 1.1, 1.8); }
      return { fx, fy, k, x: clamp(960 - fx * k, W - W * k, 0), y: clamp(540 - fy * k, H - H * k, 0) };
    };
    const shots = [{ t: 0, mode: 'wide' }, ...S.events.filter((e) => e.do === 'shot')].sort((a, b) => a.t - b.t);
    tl.set(cam, { x: 0, y: 0, scale: 1, transformOrigin: '0 0' }, 0);
    let cur = { x: 0, y: 0, k: 1 };
    const pending = [];
    // events in time order, so each shot sees where its character stands at that moment
    const evs = [...S.events].sort((a, b) => a.t - b.t);
    for (const ev of evs) {
      const c = ch[ev.who];
      if (ev.do === 'shot') pending.push({ t: ev.t, v: view(ev.mode, ev.on), mode: ev.mode });
      else if (ev.do === 'say' && c) {
        if (ev.emo) c.emo(ev.t, ev.emo);
        c.say(ev.t, ev.d, ev.mouth || []);
        for (const o of Object.values(ch)) if (o !== c) o.look(ev.t, Math.sign(c.x - o.x) * 4, 0, 0.25);
      } else if (ev.do === 'emo' && c) c.emo(ev.t, ev.emo);
      else if (ev.do === 'pose' && c) c.pose(ev.t, ev.pose, ev.d || 1.2);
      else if (ev.do === 'walk' && c) c.walk(ev.t, ev.d, ev.to);
      else if (ev.do === 'look' && c) c.look(ev.t, ev.dx, ev.dy || 0);
      else if (ev.do === 'card') g.Cards.add(tl, cards, pre, ev);
      else if (c && ['hop', 'nod', 'no'].includes(ev.do)) c[ev.do](ev.t);
      else if (c && ['sit', 'stand'].includes(ev.do)) c[ev.do](ev.t, 0.35);
      else if (c && ev.do === 'shake') c.shake(ev.t, ev.d || 0.6);
    }
    const seq = [{ t: 0, v: view('wide') }, ...pending.map((p) => ({ t: p.t, v: p.v }))].sort((a, b) => a.t - b.t);
    seq.forEach((s, i) => {
      const hold = (seq[i + 1] ? seq[i + 1].t : S.dur) - s.t;
      const mv = Math.min(0.65, hold);
      if (i > 0) tl.fromTo(cam, { x: cur.x, y: cur.y, scale: cur.k }, { x: s.v.x, y: s.v.y, scale: s.v.k, duration: mv, ease: 'power3.inOut' }, s.t);
      const k2 = s.v.k * 1.03;
      const end = { x: clamp(960 - s.v.fx * k2, W - W * k2, 0), y: clamp(540 - s.v.fy * k2, H - H * k2, 0), k: k2 };
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
    else if (S.cover_in === 'wipe') { tl.set(cover, { backgroundColor: GOLD, opacity: 1 }, 0); tl.to(cover, { x: W, duration: 0.5, ease: 'power3.inOut' }, 0); }
    if (S.cover_out === 'fade') { tl.set(cover, { backgroundColor: BLACK, opacity: 0, x: 0 }, S.dur - 0.4); tl.to(cover, { opacity: 1, duration: 0.35 }, S.dur - 0.35); }
    else if (S.cover_out === 'wipe') { tl.set(cover, { backgroundColor: GOLD, opacity: 1, x: -W }, S.dur - 0.42); tl.to(cover, { x: 0, duration: 0.4, ease: 'power3.in' }, S.dur - 0.4); }
    tl.set({}, {}, S.dur);
  }
  g.Stage = { build };
})(typeof window !== 'undefined' ? window : globalThis);
