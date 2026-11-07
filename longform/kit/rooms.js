/* Flat-vector rooms for the long-video scenes. Pure functions: Rooms.make(kind, tone, pre) -> {svg}.
   Canvas 1920x1080, wall to y=860, floor below. `pre` makes every gradient id unique across the assembled page. */
(function (g) {
  const FLOOR = 860;
  const rect = (x, y, w, h, f, rx = 0, o = '') => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${f}" ${o}/>`;
  const circ = (x, y, r, f, o = '') => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}" ${o}/>`;
  const ell = (x, y, rx, ry, f, o = '') => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${f}" ${o}/>`;
  const path = (d, f, o = '') => `<path d="${d}" fill="${f}" ${o}/>`;
  const line = (x1, y1, x2, y2, s, w, o = '') => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${s}" stroke-width="${w}" stroke-linecap="round" ${o}/>`;
  const SKY = { day: ['#7fc4f0', '#dff3ff'], evening: ['#ef8d52', '#ffd9a6'], night: ['#0a1030', '#2a3a78'], dawn: ['#e9a8b4', '#ffe6c8'] };
  const TINT = { day: '', evening: 'rgba(255,110,30,.13)', night: 'rgba(6,12,48,.46)', dawn: 'rgba(255,160,110,.10)' };

  function defs(pre, tone) {
    const [a, b] = SKY[tone] || SKY.day;
    return `<defs><linearGradient id="${pre}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient>
      <radialGradient id="${pre}-glow"><stop offset="0" stop-color="#ffe9a8" stop-opacity=".75"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/></radialGradient>
      <radialGradient id="${pre}-vig" cx=".5" cy=".5" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></radialGradient></defs>`;
  }
  const stars = (x, y, w, h) => Array.from({ length: 22 }, (_, i) => circ(x + ((i * 97 + 31) % w), y + ((i * 53 + 17) % (h * 0.7)), 1.6 + (i % 3) * 0.7, '#fff', 'opacity=".85"')).join('');
  const clouds = (x, y, s = 1) => ell(x, y, 60 * s, 22 * s, '#fff', 'opacity=".9"') + ell(x + 42 * s, y - 14 * s, 42 * s, 22 * s, '#fff', 'opacity=".9"') + ell(x - 40 * s, y - 8 * s, 36 * s, 18 * s, '#fff', 'opacity=".9"');

  function windowAt(pre, tone, x, y, w, h, frame = '#fff', skyline = true) {
    let s = rect(x, y, w, h, `url(#${pre}-sky)`);
    if (tone === 'night') s += stars(x, y, w, h);
    else s += clouds(x + w * 0.3, y + h * 0.28, w / 420) + clouds(x + w * 0.72, y + h * 0.18, w / 600);
    if (skyline) {
      const c = tone === 'night' ? '#141c44' : tone === 'evening' ? '#b0603f' : '#8fb0cb';
      for (let i = 0; i < 6; i++) s += rect(x + 12 + i * (w / 6.2), y + h * (0.55 + (i % 3) * 0.08), w / 7, h, c);
    }
    return s + rect(x, y, w, h, 'none', 6, `stroke="${frame}" stroke-width="12"`) + line(x + w / 2, y, x + w / 2, y + h, frame, 8) + line(x, y + h / 2, x + w, y + h / 2, frame, 8);
  }
  const plant = (x, y, s = 1) => rect(x - 26 * s, y - 70 * s, 52 * s, 70 * s, '#b4623f', 6 * s) + [-40, -18, 0, 20, 42].map((dx, i) => path(`M${x} ${y - 70 * s} q${dx * s} ${-(70 + (i % 2) * 40) * s} ${dx * 1.3 * s} ${-(110 + (i % 3) * 30) * s} q${-14 * s} ${60 * s} ${-dx * 0.3 * s} ${(110 + (i % 3) * 30) * s}z`, i % 2 ? '#3f9a57' : '#2f7d46')).join('');
  const frameArt = (x, y, w, h, c1, c2) => rect(x, y, w, h, '#fff', 6, 'stroke="#8b6b4a" stroke-width="10"') + rect(x + 12, y + 12, w - 24, h - 24, c1, 2) + path(`M${x + 12} ${y + h - 12}l${w * 0.3} ${-h * 0.4} ${w * 0.25} ${h * 0.25} ${w * 0.2} ${-h * 0.3} ${w * 0.25 - 24} ${h * 0.45 - 12}z`, c2);
  const lamp = (x, y, h, shade = '#f2c14e', glow = false, pre = '') => (glow ? circ(x, y - h, 150, `url(#${pre}-glow)`) : '') + rect(x - 5, y - h, 10, h, '#6b5b4a') + ell(x, y, 34, 9, '#6b5b4a') + path(`M${x - 46} ${y - h + 6}L${x - 26} ${y - h - 56}H${x + 26}L${x + 46} ${y - h + 6}z`, shade);
  const wood = (c, n = 7) => Array.from({ length: n }, (_, i) => line(0, FLOOR + 22 + i * 32, 1920, FLOOR + 22 + i * 32, c, 3, 'opacity=".5"')).join('');
  const rug = (x, y, w, h, c) => ell(x, y, w, h, c, 'opacity=".9"') + ell(x, y, w * 0.82, h * 0.7, 'none', `stroke="#fff" stroke-opacity=".35" stroke-width="6"`);

  const ROOMS = {
    living(pre, tone) {
      return rect(0, 0, 1920, FLOOR, '#e9dcc3') + rect(0, 730, 1920, 130, '#d8c5a2') + rect(0, FLOOR, 1920, 220, '#b78a5e') + wood('#9a7048') +
        windowAt(pre, tone, 1180, 150, 420, 380) + rect(1120, 120, 70, 450, '#c96b5a', 8) + rect(1590, 120, 70, 450, '#c96b5a', 8) +
        frameArt(760, 230, 190, 140, '#9ec9a4', '#5e9a6b') + frameArt(520, 290, 120, 160, '#e9c28f', '#c98b4b') +
        rect(240, 600, 580, 170, '#5b7aa6', 34) + rect(215, 700, 70, 170, '#4f6d98', 24) + rect(775, 700, 70, 170, '#4f6d98', 24) + rect(250, 730, 560, 130, '#6b8bb8', 28) +
        rect(290, 640, 200, 110, '#7c9cc8', 20) + rect(560, 640, 200, 110, '#7c9cc8', 20) + lamp(1010, 860, 330, '#f2c14e', tone === 'night', pre) +
        plant(1780, 860, 1.15) + rug(960, 1000, 560, 60, '#c2554a');
    },
    bedroom(pre, tone) {
      return rect(0, 0, 1920, FLOOR, '#cdd8ee') + rect(0, 760, 1920, 100, '#b9c7e3') + rect(0, FLOOR, 1920, 220, '#a98467') + wood('#8c6a50') +
        windowAt(pre, tone, 240, 160, 380, 340, '#f4f4f4', false) + frameArt(760, 200, 170, 230, '#f3c78e', '#d88a4a') +
        rect(1110, 600, 60, 260, '#6d4429', 8) + rect(1130, 700, 640, 160, '#8a5a3b', 10) + rect(1140, 650, 610, 100, '#f7f7f7', 22) + rect(1140, 690, 400, 70, '#e07a5f', 14) + ell(1210, 650, 74, 36, '#fff') +
        rect(960, 740, 110, 120, '#7a4f33', 8) + lamp(1015, 740, 110, '#f2c14e', tone === 'night', pre) + rug(520, 1000, 400, 48, '#6a8fd0');
    },
    hospital(pre, tone) {
      const beat = Array.from({ length: 14 }, (_, i) => `${650 + i * 11},${402 + (i === 4 ? -46 : i === 5 ? 36 : i === 6 ? -18 : 0)}`).join(' ');
      return rect(0, 0, 1920, FLOOR, '#dfeee9') + rect(0, 700, 1920, 160, '#bcd5cd') + rect(0, FLOOR, 1920, 220, '#c8d6d4') +
        Array.from({ length: 10 }, (_, i) => line(i * 220, FLOOR, i * 220 - 120, 1080, '#b4c3c1', 3)).join('') +
        windowAt(pre, tone, 170, 150, 360, 360, '#f4f9f7', false) + Array.from({ length: 6 }, (_, i) => line(170, 180 + i * 56, 530, 180 + i * 56, '#e7efed', 5)).join('') +
        rect(1630, 240, 210, 620, '#c9a98a', 6) + circ(1660, 560, 10, '#8a6a4a') +
        rect(640, 540, 14, 320, '#9aa8ad') + rect(580, 330, 190, 140, '#16222c', 14) + `<polyline points="${beat}" fill="none" stroke="#5cf29a" stroke-width="4" stroke-linejoin="round"/>` + ell(615, 860, 60, 10, '#9aa8ad') +
        rect(1000, 700, 640, 40, '#9fb1b7', 8) + rect(1010, 640, 600, 70, '#fff', 18) + rect(1010, 676, 420, 50, '#8fc1e3', 12) + ell(1550, 636, 74, 30, '#fff') + rect(1620, 560, 34, 300, '#9fb1b7', 8) +
        rect(1010, 740, 14, 120, '#7c8b90') + rect(1596, 740, 14, 120, '#7c8b90') + circ(1017, 868, 14, '#4a5559') + circ(1603, 868, 14, '#4a5559') +
        rect(1700, 380, 10, 480, '#b9c3c7') + ell(1705, 390, 34, 46, '#d9f2ff', 'opacity=".9"');
    },
    classroom(pre, tone) {
      const chalk = [0, 1, 2, 3].map((i) => line(540, 220 + i * 60, 540 + 260 + ((i * 70) % 250), 220 + i * 60, '#eef6ee', 7, 'opacity=".85"')).join('');
      return rect(0, 0, 1920, FLOOR, '#efe7cf') + rect(0, FLOOR, 1920, 220, '#d6b48c') + Array.from({ length: 12 }, (_, i) => line(i * 170, FLOOR, i * 170 - 60, 1080, '#bf9a72', 3)).join('') +
        rect(470, 130, 980, 400, '#8b5e3c', 10) + rect(490, 150, 940, 360, '#2f5d46', 6) + chalk + rect(480, 520, 960, 16, '#6f4a2e', 4) +
        circ(1590, 190, 66, '#fff', 'stroke="#555" stroke-width="10"') + line(1590, 190, 1590, 146, '#333', 6) + line(1590, 190, 1624, 206, '#333', 6) +
        windowAt(pre, tone, 60, 200, 300, 330, '#fff', false) + rect(1620, 330, 230, 530, '#9a6a44', 8) + rect(1640, 350, 190, 230, '#b88357', 6) +
        [380, 760, 1140, 1500].map((x) => rect(x, 740, 250, 24, '#a9744a', 6) + rect(x + 14, 764, 12, 96, '#6f5440') + rect(x + 224, 764, 12, 96, '#6f5440') + rect(x + 40, 700, 170, 40, '#c89460', 8)).join('');
    },
    street(pre, tone) {
      const wins = (x, y, w, h, c1, c2) => { let s = ''; for (let r = 0; r < Math.floor(h / 84); r++) for (let k = 0; k < Math.floor(w / 78); k++) s += rect(x + 20 + k * 78, y + 24 + r * 84, 44, 54, ((r * 3 + k * 5) % 4 === 0) ? c2 : c1, 4); return s; };
      const lit = tone === 'night' ? '#ffd87a' : '#cfe6f5', unlit = tone === 'night' ? '#26335f' : '#a9c7dd';
      const far = tone === 'night' ? '#18224f' : '#9bb7d1';
      return rect(0, 0, 1920, 640, `url(#${pre}-sky)`) + (tone === 'night' ? stars(0, 0, 1920, 400) : clouds(300, 130, 1.6) + clouds(1300, 90, 1.3)) +
        [0, 260, 540, 800, 1080, 1360, 1640].map((x, i) => rect(x, 330 + (i % 3) * 40, 240, 540, far)).join('') +
        rect(0, 220, 420, 640, '#c9795a') + wins(0, 220, 420, 640, unlit, lit) + rect(440, 320, 380, 540, '#e0b872') + wins(440, 320, 380, 540, unlit, lit) +
        rect(840, 170, 360, 690, '#8aa9c4') + wins(840, 170, 360, 690, unlit, lit) + rect(1220, 280, 300, 580, '#d88b7a') + wins(1220, 280, 300, 580, unlit, lit) +
        rect(1540, 200, 380, 660, '#a3b78a') + wins(1540, 200, 380, 660, unlit, lit) + rect(120, 740, 90, 120, '#6b3f2a', 4) +
        rect(0, FLOOR, 1920, 70, '#cfcfcf') + rect(0, 930, 1920, 150, '#4a4f58') + Array.from({ length: 8 }, (_, i) => rect(60 + i * 250, 1000, 130, 12, '#e8e8e8', 4)).join('') +
        rect(1280, 800, 300, 90, '#d9483b', 24) + rect(1340, 745, 170, 70, '#d9483b', 18) + rect(1360, 755, 60, 44, '#cfe6f5', 6) + rect(1430, 755, 60, 44, '#cfe6f5', 6) + circ(1340, 895, 34, '#222') + circ(1520, 895, 34, '#222') + circ(1340, 895, 14, '#aaa') + circ(1520, 895, 14, '#aaa') +
        rect(1060, 470, 14, 400, '#4b4f55') + rect(1060, 470, 90, 12, '#4b4f55') + circ(1150, 492, 22, tone === 'night' ? '#fff3b0' : '#e8e8d0') + (tone === 'night' ? circ(1150, 500, 90, `url(#${pre}-glow)`) : '');
    },
    office(pre, tone) {
      return rect(0, 0, 1920, FLOOR, '#dfe6ee') + rect(0, FLOOR, 1920, 220, '#9aa5b1') + windowAt(pre, tone, 150, 130, 760, 450, '#f4f7fb') +
        rect(1000, 150, 460, 270, '#fff', 8, 'stroke="#b9c3cf" stroke-width="10"') + path('M1040 360l90-110 70 70 80-120 110 150', 'none', 'stroke="#4a8fe0" stroke-width="8" stroke-linejoin="round"') +
        rect(1540, 200, 300, 16, '#8a6a4a') + rect(1560, 150, 40, 50, '#d9483b') + rect(1610, 140, 36, 60, '#4a8fe0') + rect(1656, 156, 44, 44, '#f2c14e') + rect(1540, 340, 300, 16, '#8a6a4a') +
        rect(1040, 700, 640, 30, '#7a5a3a', 6) + rect(1070, 730, 24, 130, '#6a4b2f') + rect(1626, 730, 24, 130, '#6a4b2f') + rect(1250, 560, 240, 150, '#222c3a', 10) + rect(1262, 572, 216, 112, '#9ad0f5', 4) + plant(1790, 860, 1.2);
    },
    kitchen(pre, tone) {
      return rect(0, 0, 1920, FLOOR, '#f6e7c8') + Array.from({ length: 14 }, (_, i) => rect(i * 140, 470, 138, 230, '#fbf5e6', 0, 'stroke="#e6d9bb" stroke-width="3"')).join('') + rect(0, FLOOR, 1920, 220, '#b99a78') + wood('#9c7e5d') +
        [150, 340, 530, 720].map((x) => rect(x, 120, 180, 240, '#c9a46a', 8) + rect(x + 70, 320, 40, 8, '#6b4e2a')).join('') + rect(100, 700, 920, 160, '#8d6e4c') + rect(80, 676, 960, 34, '#ded8c8', 6) + circ(300, 620, 56, '#9aa5ad') + rect(240, 664, 120, 12, '#555') +
        windowAt(pre, tone, 1130, 200, 300, 260, '#fff', false) + rect(1200, 720, 480, 30, '#a9744a', 6) + rect(1230, 750, 22, 110, '#7a5738') + rect(1630, 750, 22, 110, '#7a5738') + rect(1260, 620, 14, 100, '#c9a46a') + rect(1620, 620, 14, 100, '#c9a46a') + rect(1710, 280, 170, 580, '#dfe6ea', 14) + rect(1720, 520, 150, 8, '#a9b3b8');
    },
    park(pre, tone) {
      const tree = (x, s) => rect(x - 22 * s, 520 - 60 * s, 44 * s, 380 * s, '#7a5233') + circ(x, 470 - 40 * s, 140 * s, '#3f9a57') + circ(x - 90 * s, 540 - 40 * s, 100 * s, '#2f7d46') + circ(x + 100 * s, 540 - 40 * s, 104 * s, '#35904f');
      return rect(0, 0, 1920, 700, `url(#${pre}-sky)`) + (tone === 'night' ? stars(0, 0, 1920, 500) + circ(1560, 170, 54, '#fff7d6') : clouds(420, 160, 1.7) + clouds(1280, 110, 1.4) + circ(1620, 150, 64, '#ffe38a')) +
        ell(380, 760, 700, 220, '#8fc47a') + ell(1500, 790, 760, 230, '#6fae62') + tree(220, 1) + tree(1660, 0.85) + rect(0, FLOOR - 20, 1920, 240, '#78b865') + path('M700 1080L860 860H1060L1240 1080z', '#e5d5a8') +
        rect(300, 770, 270, 20, '#8a5a3b', 6) + rect(300, 730, 270, 16, '#8a5a3b', 6) + rect(320, 790, 16, 80, '#6b4a30') + rect(534, 790, 16, 80, '#6b4a30') +
        Array.from({ length: 16 }, (_, i) => circ(60 + i * 118, 900 + (i * 37) % 140, 9, ['#ff6f91', '#ffd166', '#fff'][i % 3])).join('');
    },
    cafe(pre, tone) {
      return rect(0, 0, 1920, FLOOR, '#e6d2b5') + rect(0, FLOOR, 1920, 220, '#a68a64') + wood('#8c7250') + windowAt(pre, tone, 1250, 170, 480, 360, '#6f4e37', false) +
        rect(180, 150, 520, 250, '#2f3b36', 8, 'stroke="#8b5e3c" stroke-width="12"') + [0, 1, 2, 3].map((i) => line(230, 205 + i * 46, 300 + ((i * 95) % 260) + 150, 205 + i * 46, '#f1f1e6', 7, 'opacity=".85"')).join('') +
        rect(160, 600, 780, 260, '#6f4e37', 8) + rect(140, 570, 820, 40, '#a9744a', 8) + rect(300, 520, 150, 52, '#fff', 8) + circ(640, 545, 24, '#d9483b') +
        [300, 640, 980].map((x) => line(x + 300, 0, x + 300, 150, '#555', 4) + circ(x + 300, 170, 40, '#f2c14e') + circ(x + 300, 190, 110, `url(#${pre}-glow)`)).join('') +
        [1200, 1600].map((x) => ell(x, 800, 90, 20, '#8a5a3b') + rect(x - 8, 800, 16, 70, '#6b4a30') + ell(x, 870, 60, 12, '#6b4a30')).join('');
    },
    stage(pre) {
      return rect(0, 0, 1920, 1080, '#1a1033') + rect(0, FLOOR, 1920, 220, '#2a1a52') + [420, 960, 1500].map((x, i) => path(`M${x - 30} 0L${x + 30} 0L${x + 360 * (i - 1) + 260} ${FLOOR}L${x + 360 * (i - 1) - 260} ${FLOOR}z`, '#fff', 'opacity=".07"')).join('') +
        [420, 960, 1500].map((x) => circ(x, 14, 34, '#f4e9b0')).join('') + ell(960, FLOOR + 90, 520, 60, '#fff', 'opacity=".08"');
    },
    void(pre) {
      let dots = '';
      for (let y = 60; y < 1080; y += 90) for (let x = 60; x < 1920; x += 90) dots += circ(x, y, 3, '#9fb4ff', 'opacity=".16"');
      return rect(0, 0, 1920, 1080, '#0f1530') + circ(960, 520, 640, `url(#${pre}-glow)`, 'opacity=".12"') + dots;
    },
  };
  // Where someone sits up in a bed drawn here is lf_plan.BEDS (the planner keeps everyone else clear of it).

  g.Rooms = {
    kinds: Object.keys(ROOMS),
    make(kind, tone = 'day', pre = 'r') {
      const k = ROOMS[kind] ? kind : 'living';
      const t = SKY[tone] ? tone : 'day';
      const body = ROOMS[k](pre, t) + (TINT[t] && k !== 'void' && k !== 'stage' ? rect(0, 0, 1920, 1080, TINT[t]) : '') + rect(0, 0, 1920, 1080, `url(#${pre}-vig)`);
      return { svg: `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">${defs(pre, t)}${body}</svg>` };
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
