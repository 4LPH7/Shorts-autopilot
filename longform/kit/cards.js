/* The "explanation" half of the film: animated cards laid over the picture. Cards.add(tl, host, pre, ev) with
   ev = {t, d, kind, ...data}. Everything is plain DOM on the paused timeline (no callbacks: callbacks do not fire on seek). */
(function (g) {
  const F = "font-family:'Nunito',sans-serif;";
  const INK = '#14183a', PAPER = '#fffdf5', GOLD = '#ffcc33', RED = '#e0475b', GREEN = '#3fa66a', BLUE = '#4a7bd6';
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let seq = 0;
  const el = (host, pre, html, css) => {
    const d = document.createElement('div');
    d.id = `${pre}-c${seq++}`;
    d.style.cssText = 'position:absolute;opacity:0;' + css;
    d.innerHTML = html;
    host.appendChild(d);
    return d;
  };
  const SHADOW = 'box-shadow:0 18px 50px rgba(0,0,0,.35);';
  function inout(tl, box, t, d) {
    tl.fromTo(box, { opacity: 0, y: 36, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.38, ease: 'back.out(1.5)' }, t);
    tl.to(box, { opacity: 0, y: -18, duration: 0.25, ease: 'power2.in' }, t + d - 0.25);
    tl.set(box, { opacity: 0 }, t + d);
  }
  const reveal = (tl, nodes, t, d, gap) => nodes.forEach((n, i) => tl.to(n, { clipPath: 'inset(0 0% 0 0)', duration: 0.55, ease: 'power2.out' }, t + 0.5 + i * gap));

  const KINDS = {
    title(tl, host, pre, t, d, o) {
      const dim = el(host, pre, '', 'left:0;top:0;width:1920px;height:1080px;background:rgba(8,10,30,.66);');
      const box = el(host, pre, `<div style="${F}font-weight:900;font-size:104px;line-height:1.05;color:#fff;text-align:center;text-shadow:0 6px 30px rgba(0,0,0,.45)">${esc(o.text)}</div>` +
        (o.sub ? `<div style="${F}font-weight:700;font-size:44px;color:${GOLD};text-align:center;margin-top:18px">${esc(o.sub)}</div>` : '') +
        `<div class="bar" style="height:10px;width:0;background:${GOLD};border-radius:6px;margin:26px auto 0"></div>`, 'left:190px;width:1540px;top:360px;');
      tl.fromTo(dim, { opacity: 0 }, { opacity: 1, duration: 0.3 }, t);
      tl.to(dim, { opacity: 0, duration: 0.3 }, t + d - 0.3);
      tl.set(dim, { opacity: 0 }, t + d);
      tl.fromTo(box.querySelector('.bar'), { width: 0 }, { width: 380, duration: 0.7, ease: 'power3.out' }, t + 0.3);
      inout(tl, box, t, d);
    },
    stat(tl, host, pre, t, d, o) {
      const m = /^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/.exec(String(o.value));
      const box = el(host, pre, `<div style="${F}font-weight:800;font-size:34px;color:#5a6188">${esc(o.label)}</div><div class="v" style="position:relative;height:150px;margin-top:6px"></div>`,
        `${o.side === 'left' ? 'left' : 'right'}:150px;top:130px;width:640px;padding:30px 40px;background:${PAPER};border-radius:28px;${SHADOW}border-left:14px solid ${GOLD};`);
      const v = box.querySelector('.v');
      const n = m ? 12 : 1, target = m ? parseFloat(m[2].replace(/,/g, '')) : 0, dec = m && m[2].includes('.') ? m[2].split('.')[1].length : 0;
      for (let i = 0; i < n; i++) {
        const val = target * Math.pow((i + 1) / n, 2);
        const s = document.createElement('div');
        s.style.cssText = `position:absolute;left:0;top:0;opacity:0;${F}font-weight:900;font-size:128px;color:${INK};line-height:150px;white-space:nowrap`;
        s.textContent = !m ? String(o.value) : i === n - 1 ? m[1] + m[2] + m[3] : m[1] + (dec ? val.toFixed(dec) : Math.round(val).toLocaleString('en-US')) + m[3];
        v.appendChild(s);
        tl.set(s, { opacity: 1 }, t + 0.3 + i * 0.07);
        if (i < n - 1) tl.set(s, { opacity: 0 }, t + 0.3 + (i + 1) * 0.07);
      }
      inout(tl, box, t, d);
    },
    list(tl, host, pre, t, d, o) {
      const items = o.items || [];
      const box = el(host, pre, (o.title ? `<div style="${F}font-weight:900;font-size:44px;color:${RED};padding-bottom:10px;border-bottom:4px solid #f3b8b8">${esc(o.title)}</div>` : '') +
        items.map((it, i) => `<div style="position:relative;height:76px;line-height:76px;font-size:40px;font-weight:800;color:${INK};border-bottom:3px solid #c9d7f2;padding-left:58px;${F}"><span style="position:absolute;left:0;top:0;color:${RED}">${i + 1}.</span><span class="t" style="display:inline-block;clip-path:inset(0 100% 0 0)">${esc(it)}</span></div>`).join(''),
        `${o.side === 'right' ? 'right' : 'left'}:150px;top:130px;width:780px;padding:26px 34px 30px;background:${PAPER};border-radius:18px;${SHADOW}border-left:8px solid #e56b6b;`);
      reveal(tl, [...box.querySelectorAll('.t')], t, d, Math.max(0.9, (d - 1.4) / Math.max(1, items.length)));
      inout(tl, box, t, d);
    },
    chart(tl, host, pre, t, d, o) {
      const vals = o.values || [3, 5, 4, 8, 13, 21], W = 800, H = 330, L = 30, B = 50;
      const mx = Math.max(...vals), mn = Math.min(0, ...vals);
      const pts = vals.map((v, i) => [L + (i * (W - L - 30)) / Math.max(1, vals.length - 1), 20 + (H - 20 - B) * (1 - (v - mn) / (mx - mn || 1))]);
      const dd = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join('');
      const labels = (o.labels || []).map((s, i) => `<text x="${pts[i][0]}" y="${H - 14}" text-anchor="middle" font-size="26" font-weight="800" fill="#5a6188" style="${F}">${esc(s)}</text>`).join('');
      const dots = pts.map((p, i) => `<circle class="d" cx="${p[0]}" cy="${p[1]}" r="11" fill="${i === pts.length - 1 ? RED : INK}" opacity="0"/>`).join('');
      const box = el(host, pre, (o.title ? `<div style="${F}font-weight:900;font-size:42px;color:${INK};margin-bottom:8px">${esc(o.title)}</div>` : '') +
        `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><line x1="${L}" y1="${H - B}" x2="${W - 10}" y2="${H - B}" stroke="#aab4d4" stroke-width="4"/><path class="p" d="${dd}" fill="none" stroke="${RED}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>${dots}${labels}</svg>`,
        `${o.side === 'left' ? 'left' : 'right'}:130px;top:170px;width:${W}px;padding:28px 40px 20px;background:${PAPER};border-radius:26px;${SHADOW}`);
      const run = Math.max(1, Math.min(2.4, d - 1.4));
      tl.to(box.querySelector('.p'), { strokeDashoffset: 0, duration: run, ease: 'power1.inOut' }, t + 0.5);
      box.querySelectorAll('.d').forEach((c, i) => tl.to(c, { opacity: 1, duration: 0.15 }, t + 0.5 + (i / Math.max(1, pts.length - 1)) * run));
      inout(tl, box, t, d);
    },
    compare(tl, host, pre, t, d, o) {
      const col = (c, color, mark) => `<div style="width:640px"><div style="${F}font-weight:900;font-size:42px;color:#fff;background:${color};border-radius:14px;padding:10px 24px;margin-bottom:10px">${esc(c.title)}</div>` +
        (c.items || []).map((it) => `<div style="${F}font-weight:800;font-size:36px;color:${INK};padding:12px 8px 12px 56px;border-bottom:3px solid #d5dcf2;position:relative"><span style="position:absolute;left:8px;top:8px;color:${color}">${mark}</span><span class="t" style="display:inline-block;clip-path:inset(0 100% 0 0)">${esc(it)}</span></div>`).join('') + '</div>';
      const box = el(host, pre, `<div style="display:flex;gap:44px">${col(o.left || {}, RED, '✗')}${col(o.right || {}, GREEN, '✓')}</div>`, `left:190px;top:200px;width:1380px;padding:30px 40px;background:${PAPER};border-radius:26px;${SHADOW}`);
      reveal(tl, [...box.querySelectorAll('.t')], t, d, Math.max(0.5, (d - 1.6) / Math.max(1, box.querySelectorAll('.t').length)));
      inout(tl, box, t, d);
    },
    stamp(tl, host, pre, t, d, o) {
      const c = o.color || RED;
      const box = el(host, pre, `<div class="s" style="${F}font-weight:900;font-size:150px;color:${c};border:16px solid ${c};border-radius:24px;padding:6px 48px;letter-spacing:.04em">${esc(o.text)}</div>`, 'left:0;top:380px;width:1920px;display:flex;justify-content:center;');
      tl.set(box, { opacity: 1 }, t);
      tl.fromTo(box.querySelector('.s'), { scale: 3, rotation: -20, opacity: 0 }, { scale: 1, rotation: -8, opacity: 1, duration: 0.22, ease: 'power4.in' }, t);
      tl.to(box, { opacity: 0, duration: 0.25 }, t + d - 0.25);
    },
    year(tl, host, pre, t, d, o) {
      const box = el(host, pre, `<div style="${F}font-weight:900;font-size:92px;color:#fff;letter-spacing:.02em">${esc(o.text)}</div>`, `left:150px;top:100px;padding:6px 44px;background:${INK};border-radius:22px;border-bottom:8px solid ${GOLD};${SHADOW}`);
      inout(tl, box, t, d);
    },
    quote(tl, host, pre, t, d, o) {
      const box = el(host, pre, `<div style="${F}font-weight:900;font-size:120px;color:${GOLD};line-height:.6">“</div><div style="${F}font-weight:800;font-size:56px;line-height:1.25;color:${INK}">${esc(o.text)}</div>` + (o.who ? `<div style="${F}font-weight:700;font-size:34px;color:#5a6188;margin-top:16px">— ${esc(o.who)}</div>` : ''),
        `left:330px;top:260px;width:1260px;padding:40px 60px 44px;background:${PAPER};border-radius:26px;${SHADOW}`);
      inout(tl, box, t, d);
    },
  };
  g.Cards = { kinds: Object.keys(KINDS), add(tl, host, pre, ev) { const k = KINDS[ev.kind] || KINDS.title; k(tl, host, pre, ev.t, ev.d, ev); } };
})(typeof window !== 'undefined' ? window : globalThis);
