/* The puppet: a flat-vector character drawn from a small "look" description. Rig.svg(id, look) returns one <g> whose
   parts have ids `${id}-<part>`; Acts (acts.js) animates them. Origin = centre of the feet, y grows downward.
   Pivots are given in puppet space with svgOrigin, so every part stays valid when its parent moves. */
(function (g) {
  const SKIN = ['#f6d3b3', '#e8b98d', '#cf9a6b', '#a06a44', '#6b4529'];
  const SHADE = ['#e9bf9a', '#d6a273', '#b9814f', '#865230', '#53341f'];
  const DARK = '#2b2230';
  const rect = (x, y, w, h, f, rx = 0, o = '') => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${f}" ${o}/>`;
  const circ = (x, y, r, f, o = '') => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}" ${o}/>`;
  const ell = (x, y, rx, ry, f, o = '') => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${f}" ${o}/>`;
  const path = (d, f, o = '') => `<path d="${d}" fill="${f}" ${o}/>`;
  const shade = (hex, k) => '#' + [1, 3, 5].map((i) => Math.max(0, Math.min(255, Math.round(parseInt(hex.slice(i, i + 2), 16) * k))).toString(16).padStart(2, '0')).join('');

  const PIVOT = { // pivots in puppet space
    legL: [-15, -130], legR: [15, -130], torso: [0, -130], armL: [-35, -224], armR: [35, -224],
    foreL: [-35, -170], foreR: [35, -170], head: [0, -248], nod: [0, -248], eyeL: [-14, -290], eyeR: [14, -290], body: [0, 0],
  };

  function hair(style, c, id) {
    const back = { long: path('M-44 -290C-52 -330 -20 -340 0 -338C22 -340 52 -330 44 -290L50 -214C30 -204 26 -240 0 -244C-26 -240 -30 -204 -50 -214z', c), bun: circ(0, -340, 22, c), curly: [-34, -12, 12, 34].map((x, i) => circ(x, -330 + (i % 2) * 6, 22, c)).join('') }[style] || '';
    const front = {
      short: path('M-40 -292C-42 -334 -10 -344 0 -344C14 -344 44 -334 40 -292C28 -312 14 -318 0 -318C-14 -318 -30 -312 -40 -292z', c),
      spiky: path('M-40 -296L-34 -346L-18 -322L-6 -354L8 -324L22 -352L30 -322L44 -340L40 -296C26 -314 -26 -314 -40 -296z', c),
      long: path('M-40 -294C-40 -332 -8 -342 0 -342C12 -342 42 -334 40 -294C26 -318 -26 -318 -40 -294z', c),
      bun: path('M-40 -294C-40 -332 -8 -342 0 -342C12 -342 42 -334 40 -294C26 -318 -26 -318 -40 -294z', c),
      curly: path('M-42 -294C-46 -330 -10 -346 0 -346C12 -346 46 -330 42 -294C26 -316 -26 -316 -42 -294z', c),
      cap: path('M-42 -300C-40 -346 40 -346 42 -300z', c) + rect(30, -312, 44, 12, shade(c, 0.85), 6),
      elder: path('M-38 -300C-30 -318 -12 -322 0 -320C12 -322 30 -318 38 -300C34 -314 20 -334 0 -334C-20 -334 -34 -314 -38 -300z', c),
    }[style] || '';
    return { back, front };
  }

  function svg(id, L) {
    const sk = SKIN[L.skin ?? 1], sh = SHADE[L.skin ?? 1];
    const col = L.color || '#4a7bd6', pants = L.pants || '#3a4152', shoes = L.shoes || '#2a2a33', hc = L.hair_color || '#3a2a1c';
    const top = L.top || 'tee';
    const longSleeve = ['suit', 'hoodie', 'coat', 'uniform'].includes(top);
    const dress = top === 'dress';
    const stick = L.style === 'stick';                    // line-art body, outlined head: same parts and pivots, so every act still works
    const LINE = DARK, eyeEdge = stick ? `stroke="${LINE}" stroke-width="2.6"` : '';
    const hh = hair(L.hair || 'short', hc);
    const p = (n) => `id="${id}-${n}"`;
    const legs = ['L', 'R'].map((s) => {
      if (stick) {
        const x = s === 'L' ? -15 : 15, f = s === 'L' ? -34 : 34;
        return `<g ${p('leg' + s)}><line x1="${x}" y1="-130" x2="${x}" y2="-18" stroke="${LINE}" stroke-width="10" stroke-linecap="round"/><line x1="${x}" y1="-14" x2="${f}" y2="-14" stroke="${LINE}" stroke-width="10" stroke-linecap="round"/></g>`;
      }
      const x = s === 'L' ? -28 : 2;
      return `<g ${p('leg' + s)}>${rect(x, -130, 26, 108, dress ? sk : pants, 13)}${ell(x + 13 + (s === 'L' ? -4 : 4), -10, 22, 11, shoes)}</g>`;
    }).join('');
    const arms = ['L', 'R'].map((s) => {
      const x = s === 'L' ? -46 : 24, hx = s === 'L' ? -35 : 35;
      if (stick) return `<g ${p('arm' + s)}><line x1="${hx}" y1="-224" x2="${hx}" y2="-170" stroke="${LINE}" stroke-width="9" stroke-linecap="round"/><g ${p('fore' + s)}><line x1="${hx}" y1="-170" x2="${hx}" y2="-116" stroke="${LINE}" stroke-width="9" stroke-linecap="round"/>${circ(hx, -110, 8, LINE)}</g></g>`;
      return `<g ${p('arm' + s)}>${rect(x, -230, 22, 62, col, 11)}<g ${p('fore' + s)}>${rect(hx - 9.5, -178, 19, 62, longSleeve ? col : sk, 9.5)}${circ(hx, -112, 10.5, sk)}</g></g>`;
    }).join('');
    let torso = path('M-37 -228C-40 -236 -30 -240 0 -240C30 -240 40 -236 37 -228L29 -130C10 -124 -10 -124 -29 -130z', col);
    if (top === 'suit') torso += path('M-14 -240L0 -190L14 -240L8 -240L0 -214L-8 -240z', '#fff') + path('M-3 -214L3 -214L6 -150L0 -142L-6 -150z', '#c7414e');
    if (top === 'hoodie') torso += path('M-24 -240C-20 -218 20 -218 24 -240z', shade(col, 0.8)) + rect(-18, -172, 36, 26, shade(col, 0.85), 8);
    if (top === 'coat') torso = path('M-39 -228C-42 -236 -30 -240 0 -240C30 -240 42 -236 39 -228L36 -70C12 -64 -12 -64 -36 -70z', col) + rect(-36, -150, 72, 10, shade(col, 0.7));
    if (top === 'apron') torso += path('M-24 -226L24 -226L28 -110L-28 -110z', '#f4f4f0');
    if (dress) torso = path('M-37 -228C-40 -236 -30 -240 0 -240C30 -240 40 -236 37 -228L60 -78C20 -68 -20 -68 -60 -78z', col);
    if (top === 'uniform') torso += rect(-34, -206, 68, 7, '#f2c14e');
    if (stick) {                                          // a shoulder bar and neck in line colour, then the outfit as one thick coloured stroke
      torso = `<line x1="-35" y1="-224" x2="35" y2="-224" stroke="${LINE}" stroke-width="9" stroke-linecap="round"/><line x1="0" y1="-252" x2="0" y2="-236" stroke="${LINE}" stroke-width="9" stroke-linecap="round"/>`
        + (dress ? path('M-4 -196L4 -196L52 -92L-52 -92z', col) : '')
        + `<line x1="0" y1="-236" x2="0" y2="${top === 'coat' ? -84 : -138}" stroke="${col}" stroke-width="${top === 'coat' ? 30 : 26}" stroke-linecap="round"/>`
        + (top === 'suit' ? path('M-4 -228L4 -228L7 -176L0 -166L-7 -176z', '#c7414e') : '')
        + (top === 'hoodie' ? path('M-15 -240C-11 -222 11 -222 15 -240z', shade(col, 0.75)) : '')
        + (top === 'apron' ? rect(-15, -224, 30, 96, '#f4f4f0', 10) : '')
        + (top === 'uniform' ? rect(-14, -204, 28, 6, '#f2c14e') : '');
    }
    const acc = (L.acc || '').split(',');
    const glasses = acc.includes('glasses') ? `<g fill="none" stroke="${DARK}" stroke-width="3.4">${circ(-14, -290, 13, 'none')}${circ(14, -290, 13, 'none')}<path d="M-1 -290h2"/></g>` : '';
    const beard = acc.includes('beard') ? path('M-34 -280C-34 -246 -16 -238 0 -238C16 -238 34 -246 34 -280C26 -262 14 -256 0 -256C-14 -256 -26 -262 -34 -280z', hc) : '';
    const hat = acc.includes('hat') ? rect(-48, -322, 96, 14, '#7a5233', 6) + rect(-30, -366, 60, 48, '#8a6040', 10) : '';
    const mouthC = `stroke="${DARK}" stroke-width="3.4" stroke-linecap="round" fill="none"`;
    const face = stick ? `<ellipse cx="0" cy="-286" rx="37" ry="38" fill="${sk}" stroke="${LINE}" stroke-width="6"/>`
      : ell(0, -286, 38, 39, sk) + circ(-38, -284, 8, sk) + circ(38, -284, 8, sk) + ell(0, -272, 4, 3, sh);
    const head = `<g ${p('head')}><g ${p('nod')}>${hh.back}${face}
      <g ${p('eyeL')}>${ell(-14, -290, 8.5, 10.5, '#fff', eyeEdge)}<circle ${p('pupL')} cx="-14" cy="-290" r="4.8" fill="${DARK}"/></g>
      <g ${p('eyeR')}>${ell(14, -290, 8.5, 10.5, '#fff', eyeEdge)}<circle ${p('pupR')} cx="14" cy="-290" r="4.8" fill="${DARK}"/></g>
      <line ${p('browL')} x1="-23" y1="-308" x2="-6" y2="-308" stroke="${shade(hc, 0.8)}" stroke-width="4.6" stroke-linecap="round"/>
      <line ${p('browR')} x1="6" y1="-308" x2="23" y2="-308" stroke="${shade(hc, 0.8)}" stroke-width="4.6" stroke-linecap="round"/>
      <g ${p('mouth')} transform="translate(0 -263)">
        <path ${p('mc0')} d="M-10 0Q0 3 10 0" ${mouthC}/><path ${p('mc1')} d="M-12 -1Q0 10 12 -1" ${mouthC} opacity="0"/><path ${p('mc2')} d="M-10 5Q0 -3 10 5" ${mouthC} opacity="0"/>
        <ellipse ${p('m1')} cx="0" cy="1" rx="9" ry="5" fill="#5a1f1f" opacity="0"/>
        <g ${p('m2')} opacity="0"><ellipse cx="0" cy="3" rx="12" ry="11" fill="#5a1f1f"/><ellipse cx="0" cy="9" rx="7" ry="4" fill="#e0667a"/></g>
        <circle ${p('m3')} cx="0" cy="3" r="7" fill="#5a1f1f" opacity="0"/>
        <g ${p('mB')} opacity="0"><ellipse cx="0" cy="1.5" rx="11" ry="4.6" fill="#5a1f1f"/><rect x="-8" y="-2.4" width="16" height="3.2" rx="1.2" fill="#fff"/></g>
        <g ${p('mC')} opacity="0"><ellipse cx="0" cy="2.5" rx="11.5" ry="7.5" fill="#5a1f1f"/><rect x="-7.5" y="-4.4" width="15" height="3.2" rx="1.2" fill="#fff"/></g>
        <g ${p('mF')} opacity="0"><ellipse cx="0" cy="2" rx="6" ry="6.5" fill="#b4545e"/><ellipse cx="0" cy="2" rx="3.4" ry="4" fill="#5a1f1f"/></g>
        <g ${p('mG')} opacity="0"><path d="M-10 2Q0 6 10 2" ${mouthC}/><rect x="-6.5" y="-2.2" width="13" height="4" rx="1.4" fill="#fff"/></g>
        <g ${p('mH')} opacity="0"><ellipse cx="0" cy="2.5" rx="10.5" ry="7.5" fill="#5a1f1f"/><ellipse cx="0" cy="-1" rx="5.5" ry="3.6" fill="#e0667a"/></g>
      </g>${beard}${glasses}${hh.front}${hat}</g></g>`;
    // a blanket for sitting up in bed: over the lap and draped down the mattress side, under the arms (hands rest on it)
    const blanket = `<path ${p('blanket')} d="M-56 -60L-56 -150Q-44 -164 0 -162L160 -154Q215 -182 262 -152Q310 -146 340 -128L346 -60z" fill="#8fc1e3" opacity="0"/>`;
    const body = `<g ${p('body')}>${legs}<g ${p('torso')}>${torso}${blanket}${arms}${head}</g></g>`;
    const chair = `<g ${p('chair')} opacity="0">${rect(-52, -72, 104, 14, '#8a5a3b', 5)}${rect(-46, -58, 12, 58, '#6b4429')}${rect(34, -58, 12, 58, '#6b4429')}${rect(-46, -190, 12, 120, '#6b4429', 5)}</g>`;
    return `<g ${p('root')}>${ell(0, 0, 64, 11, 'rgba(0,0,0,.2)', p('shadow'))}${chair}${body}</g>`;
  }

  g.Rig = {
    PIVOT, SKIN, DARK, svg,
    /* Parts of puppet `id` as elements, with their pivots applied. Call once, after the markup is in the DOM. */
    parts(id) {
      const out = {};
      for (const n of ['root', 'shadow', 'chair', 'body', 'legL', 'legR', 'torso', 'blanket', 'armL', 'armR', 'foreL', 'foreR', 'head', 'nod', 'eyeL', 'eyeR', 'pupL', 'pupR',
        'browL', 'browR', 'mouth', 'mc0', 'mc1', 'mc2', 'm1', 'm2', 'm3', 'mB', 'mC', 'mF', 'mG', 'mH']) out[n] = document.getElementById(`${id}-${n}`);
      for (const [n, [x, y]] of Object.entries(PIVOT)) if (out[n]) g.gsap.set(out[n], { svgOrigin: `${x} ${y}` });
      g.gsap.set(out.root, { svgOrigin: '0 0' });
      g.gsap.set([out.pupL, out.pupR], { svgOrigin: '0 -290' });
      return out;
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
