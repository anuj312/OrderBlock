/* Order X-Ray client. Plain JS + canvas, no framework. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  // Canvas palette per theme (CSS uses the matching custom properties in xray.css)
  const THEMES = {
    dark: {
      bull: '#21e38b', bear: '#ff3d5e', amber: '#ffb020', yellow: '#ffd23f', blue: '#3d7bff',
      text: '#d6e4dd', muted: '#6b7f77', strong: '#ffffff', grid: 'rgba(160,255,210,0.07)',
      bullRgb: '33,227,139', bearRgb: '255,61,94', ink: '255,255,255', shade: '0,0,0',
      plot: 'rgba(2,6,6,0.55)', glow: 1, sweep: '120,255,200', dot: '#ffffff',
      candleUp: '#c9ffe4', candleUp2: '#7df0b8', candleDn: '#ff6b84', dim: 0.17, vp: 0.42,
    },
    light: {
      bull: '#0a9e58', bear: '#de2848', amber: '#c97a00', yellow: '#b88600', blue: '#2a62e6',
      text: '#1d2a25', muted: '#64746d', strong: '#0b1512', grid: 'rgba(20,60,45,0.09)',
      bullRgb: '10,158,88', bearRgb: '222,40,72', ink: '15,30,25', shade: '255,255,255',
      plot: 'rgba(255,255,255,0.72)', glow: 0.25, sweep: '10,158,88', dot: null,
      candleUp: '#0a9e58', candleUp2: '#0a9e58', candleDn: '#de2848', dim: 0.24, vp: 0.34,
    },
  };
  const theme = () => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
  let C = THEMES[theme()];
  const A = (rgb, a) => `rgba(${rgb},${a})`;
  const sideRgb = x => (x.side === 'bull' ? C.bullRgb : C.bearRgb);
  const POLL_MS = 2000;
  const SESSION_SEC = 22500; // 09:15 -> 15:30
  const S = { board: null, hist: null, histKey: null, by: {}, charts: {}, hlSector: null, pop: null, mobile: false };

  // ----------------------------------------------------------------- format
  const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const px = v => (v == null ? '–' : nf2.format(v));
  const pct = (v, d = 2) => (v == null ? '–' : (v >= 0 ? '+' : '') + v.toFixed(d) + '%');
  const sgn = (v, d = 2) => (v == null ? '–' : (v >= 0 ? '+' : '') + nf2.format(v));
  const big = v => {
    if (v == null) return '–';
    const a = Math.abs(v), s = v >= 0 ? '+' : '-';
    if (a >= 1e7) return s + (a / 1e7).toFixed(2) + 'Cr';
    if (a >= 1e5) return s + (a / 1e5).toFixed(2) + 'L';
    if (a >= 1e3) return s + (a / 1e3).toFixed(1) + 'K';
    return s + a.toFixed(0);
  };
  const tfmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
  const tfmtS = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const hhmm = ts => tfmt.format(new Date(ts * 1000));
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const dots = cv => '●'.repeat(Math.max(1, Math.ceil(cv / 20)));
  const initials = s => s.replace(/[^A-Z0-9]/g, '').slice(0, 2);
  const hue = s => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360; return h; };
  const side = x => (x.side === 'bull' ? C.bull : C.bear);

  function fitCanvas(cv) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h, dpr };
  }

  // ----------------------------------------------------------------- data
  async function poll() {
    try {
      const r = await fetch('/api/board', { cache: 'no-store' });
      if (r.ok) {
        const b = await r.json();
        if (b && b.status) await onBoard(b);
      }
    } catch (e) { setPhase('OFFLINE', ''); }
    setTimeout(poll, POLL_MS);
  }

  async function loadHistory(force) {
    const b = S.board;
    const key = Math.floor(b.status.now / 300) + ':' + b.status.session;
    if (!force && key === S.histKey && S.hist) return;
    try {
      const r = await fetch('/api/history', { cache: 'no-store' });
      if (r.ok) { S.hist = await r.json(); S.histKey = key; }
    } catch (e) { /* keep previous */ }
  }

  async function onBoard(b) {
    S.board = b;
    S.by = Object.fromEntries(b.stocks.map(x => [x.s, x]));
    await loadHistory(false);
    renderHeader(b);
    renderTiles('bull'); renderTiles('bear');
    renderCards('bull'); renderCards('bear');
    xray.rebuild();
    renderSectors();
    pulse.draw();
    if (S.pop) refreshPop();
  }

  // ----------------------------------------------------------------- header
  function setPhase(text, cls) {
    const el = $('#phase'); el.textContent = text; el.className = 'phase ' + (cls || '');
  }
  function renderHeader(b) {
    const st = b.status;
    if (st.mode === 'demo') setPhase('DEMO · ' + st.phase, 'demo');
    else setPhase(st.phase === 'LIVE' ? 'LIVE' : st.phase === 'PRE' ? 'PRE-OPEN' : 'CLOSED · ' + st.session, st.phase === 'LIVE' ? 'live' : '');
    $('#clock').textContent = tfmtS.format(new Date(st.now * 1000)) + ' IST';
    $('#load').textContent = st.loaded < st.total ? `history ${st.loaded}/${st.total}` : (st.ticker && st.mode === 'kite' && st.ticker !== 'connected' ? 'ticker ' + st.ticker : '');
    $('#nBull').textContent = b.counts.bull; $('#nBear').textContent = b.counts.bear;
    $('#breadthUp').style.width = (b.counts.n ? b.counts.up / b.counts.n * 100 : 50) + '%';
    $('#q').placeholder = `Search ${b.counts.n} stocks`;
    const ban = $('#banner');
    if (st.error) { ban.hidden = false; ban.textContent = st.error; } else ban.hidden = true;
  }

  // ----------------------------------------------------------------- tiles
  function columns(n) { // ranks per tile column, left -> right (small ranks sit next to the cards)
    const c1 = Math.min(3, n), c2 = Math.min(3, n - c1), c3 = n - c1 - c2;
    const r = (a, k) => Array.from({ length: k }, (_, i) => a + i);
    return [c3 ? ['c3', r(c1 + c2 + 1, c3)] : null, c2 ? ['c2', r(c1 + 1, c2)] : null, ['c1', r(1, c1)]].filter(Boolean);
  }
  function buildTiles(el, n) {
    const cols = columns(n);
    el.style.gridTemplateColumns = cols.map(([c]) => ({ c1: '1.2fr', c2: '.95fr', c3: '.78fr' }[c])).join(' ');
    el.innerHTML = cols.map(([c, ranks]) =>
      `<div class="tcol ${c}" style="grid-template-rows:repeat(${ranks.length},1fr)">` +
      ranks.map(k => `<div class="tile empty" data-rank="${k}"><canvas class="vp"></canvas>
        <div class="t-row"><span class="sym">–</span><span class="rk">${String(k).padStart(2, '0')}</span></div>
        <div class="t-chg"></div><div class="t-bu"></div><span class="dr"></span><div class="t-px"></div></div>`).join('') +
      '</div>').join('');
    el.dataset.n = n;
  }
  function renderTiles(sd) {
    const b = S.board, el = sd === 'bull' ? $('#tilesBull') : $('#tilesBear');
    const n = b.rules.board;
    if (+el.dataset.n !== n) buildTiles(el, n);
    const list = b.boards[sd], picks = new Set(b.picks[sd]), entered = new Set(b.entered);
    el.querySelectorAll('.tile').forEach(t => {
      const k = +t.dataset.rank, sym = list[k - 1], x = sym && S.by[sym];
      if (!x) { t.className = 'tile empty'; t.removeAttribute('data-s'); return; }
      if (t.dataset.s && t.dataset.s !== sym) { t.classList.remove('swap'); void t.offsetWidth; t.classList.add('swap'); }
      t.dataset.s = sym;
      t.classList.remove('empty');
      t.classList.toggle('pick', picks.has(sym));
      t.classList.toggle('enter', entered.has(sym));
      $('.sym', t).textContent = sym;
      const c = $('.t-chg', t); c.textContent = pct(x.chg); c.className = 't-chg ' + (x.chg >= 0 ? 'up' : 'dn');
      $('.t-bu', t).innerHTML = x.bu ? esc(x.bu) + (k <= 3 ? `<span class="dots">${dots(x.cv)}</span>` : '') : '';
      $('.t-bu', t).style.display = x.bu ? '' : 'none';
      const dr = $('.dr', t);
      dr.textContent = x.dr ? (x.dr > 0 ? '▲' + x.dr : '▼' + -x.dr) : '';
      dr.className = 'dr ' + (x.dr > 0 ? 'up' : 'dn');
      $('.t-px', t).textContent = px(x.ltp);
      drawProfile($('canvas', t), b.details[sym], x);
    });
  }
  function drawProfile(cv, det, x) {
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const vp = det && det.vp;
    if (!vp) return;
    const n = vp.b.length, top = 4, bh = (h - top - 2) / n;
    vp.b.forEach(([v, u], i) => {
      const y = h - 2 - (i + 1) * bh, bw = v * w * 0.9;
      ctx.fillStyle = A(C.bullRgb, C.vp); ctx.fillRect(0, y + 1, bw * u, Math.max(1, bh - 1.5));
      ctx.fillStyle = A(C.bearRgb, C.vp); ctx.fillRect(bw * u, y + 1, bw * (1 - u), Math.max(1, bh - 1.5));
    });
    const yl = h - 2 - (x.ltp - vp.lo) / (vp.hi - vp.lo) * (h - top - 2);
    ctx.strokeStyle = A(C.ink, 0.6); ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, yl); ctx.lineTo(w, yl); ctx.stroke(); ctx.setLineDash([]);
    const g = ctx.createLinearGradient(0, 0, w, 0); // shade the left side so text stays legible
    g.addColorStop(0, A(C.shade, 0.35)); g.addColorStop(0.6, A(C.shade, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  }

  // ----------------------------------------------------------------- cards
  function renderCards(sd) {
    const b = S.board, el = sd === 'bull' ? $('#cardsBull') : $('#cardsBear');
    const picks = b.picks[sd], n = b.rules.picks;
    if (el.children.length !== n) el.innerHTML = Array.from({ length: n }, () => '<article class="card empty"></article>').join('');
    [...el.children].forEach((card, i) => {
      const sym = picks[i], x = sym && S.by[sym], det = sym && b.details[sym];
      if (!x || !det || !det.setup) {
        card.className = 'card empty'; card.removeAttribute('data-s');
        card.innerHTML = `<span>Waiting for a clean ${sd === 'bull' ? 'bullish' : 'bearish'} setup…</span>`;
        return;
      }
      const s = det.setup, L = s.labels, isB = sd === 'bull';
      card.className = 'card'; card.dataset.s = sym;
      const name = { stop: isB ? 'SUPPORT 1' : 'RESISTANCE 1', t1: isB ? 'RESISTANCE 1' : 'SUPPORT 1', t2: isB ? 'RESISTANCE 2' : 'SUPPORT 2' };
      const span = Math.abs(s.t2 - s.stop) || 1;
      const pos = Math.max(0, Math.min(100, (isB ? (x.ltp - s.stop) : (s.stop - x.ltp)) / span * 100));
      card.innerHTML = `
        <div class="cd-l">
          <div class="cd-name"><span class="mono-logo" style="background:linear-gradient(135deg,hsl(${hue(sym)} 70% 50%),hsl(${hue(sym)} 70% 30%))">${esc(initials(sym))}</span>
            <div style="min-width:0"><b>${esc(sym)}</b><small>${esc(x.secName)}</small></div></div>
          <div class="cd-badge"><span class="badge">${isB ? 'BULLISH' : 'BEARISH'}</span><span class="ring" style="--v:${x.cv}"><i>${x.cv}</i></span></div>
          <div class="cd-big">${pct(x.chg)}</div>
          <div class="cd-px">₹${px(x.ltp)} <span>${sgn(x.chgAbs)}</span><em>P${x.p.toFixed(1)}</em></div>
        </div>
        <div class="cd-r">
          <div class="cd-tag">${x.bu ? `<b>${esc(x.bu)}</b>` : ''}OI ${pct(x.oiChg, 1)} · Δ ${big(x.oiAbs)}</div>
          <canvas class="cd-mini"></canvas>
        </div>
        <div class="cd-lv">
          <div><small>${name.stop}</small><b class="stop">${px(s.stop)}</b></div>
          <div><small>ZONE</small><b>${px(s.zone[0])}–${px(s.zone[1])}</b></div>
          <div><small>${name.t1}${s.proj[0] ? '*' : ''}</small><b>${px(s.t1)}</b></div>
          <div><small>${name.t2}${s.proj[1] ? '*' : ''}</small><b>${px(s.t2)}</b></div>
          <div><small>RISK</small><b>${s.riskPct == null ? '–' : s.riskPct.toFixed(2) + '%'}</b></div>
          <div><small>R:R</small><b>${s.rr == null ? '–' : '1:' + s.rr.toFixed(1)}</b></div>
        </div>
        <div class="cd-bar" title="Price between ${L.stop} and ${L.t2}"><i style="left:${pos}%"></i></div>`;
      drawMini($('canvas', card), det, x);
    });
  }
  function drawMini(cv, det, x) {
    const { ctx, w, h } = fitCanvas(cv);
    const sp = det.spark.filter(v => v != null), s = det.setup;
    if (sp.length < 2) return;
    const lv = [s.stop, s.t1, s.t2, s.zone[0], s.zone[1]].filter(v => v != null);
    let lo = Math.min(...sp, ...lv), hi = Math.max(...sp, ...lv);
    const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const n = Math.max(sp.length + 6, 30);
    const X = i => 2 + i / (n - 1) * (w - 4), Y = v => h - 3 - (v - lo) / (hi - lo) * (h - 6);
    const col = side(x);
    ctx.fillStyle = A(sideRgb(x), 0.16);
    const zx = X(Math.max(0, sp.length - 12));
    ctx.fillRect(zx, Y(s.zone[1]), w - zx, Math.max(2, Y(s.zone[0]) - Y(s.zone[1])));
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, A(sideRgb(x), 0.45));
    grad.addColorStop(1, A(sideRgb(x), 0));
    ctx.beginPath(); ctx.moveTo(X(0), h);
    sp.forEach((v, i) => ctx.lineTo(X(i), Y(v))); ctx.lineTo(X(sp.length - 1), h); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); sp.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.shadowColor = col; ctx.shadowBlur = 6 * C.glow; ctx.stroke(); ctx.shadowBlur = 0;
    const lines = [[s.stop, C.yellow, s.labels.stop], [s.t1, A(C.ink, 0.8), s.labels.t1], [s.t2, A(C.ink, 0.8), s.labels.t2]];
    ctx.font = '600 8px JetBrains Mono, monospace'; ctx.textAlign = 'right';
    const used = [];
    for (const [v, c, l] of lines) {
      if (v == null) continue;
      const y = Y(v);
      ctx.strokeStyle = c; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(zx, y); ctx.lineTo(w, y); ctx.stroke();
      if (used.some(u => Math.abs(u - y) < 9)) continue; // keep labels legible
      used.push(y);
      ctx.fillStyle = c; ctx.fillText(`${l} ${px(v)}`, w - 2, y - 2);
    }
    const lx = X(sp.length - 1), ly = Y(sp[sp.length - 1]);
    ctx.fillStyle = C.strong; ctx.beginPath(); ctx.arc(lx, ly, 2.4, 0, 7); ctx.fill();
  }

  // ----------------------------------------------------------------- sectors
  // Aligned list: gainers stacked down from the top, losers stacked down from the zero line.
  function renderSectors() {
    const b = S.board, el = $('#sectors'), g = xray.geom;
    if (!g) return;
    const top = g.y0 - g.areaTop, bottom = g.y1 - g.areaTop, zero = g.yz - g.areaTop;
    const ROW = Math.max(20, Math.min(26, (bottom - top - 12) / Math.max(1, b.sectors.length))); // shrink only if it can't fit
    const byChg = (a, c) => c.chg - a.chg;
    const ups = b.sectors.filter(s => s.chg >= 0).sort(byChg);
    const dns = b.sectors.filter(s => s.chg < 0).sort(byChg);
    const upEnd = top + ups.length * ROW;
    let dnStart = Math.max(zero + 8, upEnd + 10);
    if (dnStart + dns.length * ROW > bottom) dnStart = Math.max(upEnd + 10, bottom - dns.length * ROW);
    const items = [...ups.map((s, i) => ({ s, y: top + i * ROW })), ...dns.map((s, i) => ({ s, y: dnStart + i * ROW }))];
    el.style.setProperty('--secw', Math.round(g.secW - 10) + 'px');
    const have = new Map([...el.children].map(c => [c.dataset.id, c]));
    for (const { s, y } of items) {
      let d = have.get(s.id);
      if (!d) {
        d = document.createElement('div'); d.dataset.id = s.id; el.appendChild(d);
        d.addEventListener('click', () => { S.hlSector = S.hlSector === s.id ? null : s.id; xray.rebuild(); renderSectors(); });
      }
      have.delete(s.id);
      d.className = 'sec ' + (s.chg >= 0 ? 'up' : 'dn') + (s.index ? ' idx' : '') + (S.hlSector === s.id ? ' on' : '');
      d.style.top = y + 'px';
      d.title = `${s.name}: avg ${pct(s.chg)}, ${s.up}/${s.n} up. Click to highlight.`;
      d.innerHTML = `<div class="nm"><span>${esc(s.name)}</span><b>${pct(s.chg)}</b></div><div class="cells">${s.cells.map(([sym, c]) => `<i class="${c >= 0 ? 'u' : ''}" title="${esc(sym)} ${pct(c)}"></i>`).join('')}</div>`;
    }
    have.forEach(d => d.remove());
  }

  // ----------------------------------------------------------------- x-ray canvas
  const xray = {
    cv: null, off: null, links: [], geom: null, sorted: [], t0: 0,
    init() {
      this.cv = $('#xray'); this.off = document.createElement('canvas');
      requestAnimationFrame(ts => this.frame(ts));
    },
    rebuild() {
      const b = S.board; if (!b) return;
      const stage = $('#stage'), sr = stage.getBoundingClientRect(), ar = $('#xarea').getBoundingClientRect();
      this.cv.style.width = sr.width + 'px'; this.cv.style.height = stage.scrollHeight + 'px';
      const { w, h, dpr } = fitCanvas(this.cv);
      this.off.width = this.cv.width; this.off.height = this.cv.height;
      const o = this.off.getContext('2d'); o.setTransform(dpr, 0, 0, dpr, 0, 0); o.clearRect(0, 0, w, h);
      const L = ar.left - sr.left, T = ar.top - sr.top, W = ar.width, Hh = ar.height;
      const secW = Math.round(Math.max(130, Math.min(200, W * 0.34)));
      const g = this.geom = {
        areaTop: T, left: L, right: L + W, axisX: L + 10, colX: L + W - 40, colW: 30,
        y0: T + 18, y1: T + Hh - 24, secW,
      };
      g.x0 = L + 22 + secW + 10;
      g.x1 = g.colX - 8;
      const plotW = g.x1 - g.x0;
      g.xf = g.x1 - Math.max(36, Math.min(80, plotW * 0.14)); // "now": lines then curve into their rank row
      const n = b.stocks.length, H = g.y1 - g.y0, rowH = H / n;
      g.yz = g.y0 + (b.counts.bull / Math.max(1, n)) * H; // split matches the ranked column
      const yz = g.yz;
      this.sorted = b.stocks.map(x => x.sc);
      this.t0 = b.t0;
      const now = Math.min(b.status.now, b.t0 + SESSION_SEC);
      const tspan = Math.max(300, now - b.t0);
      const X = t => g.x0 + Math.max(0, Math.min(1, (t - b.t0) / tspan)) * (g.xf - g.x0);
      g.X = X;
      const rowY = i => g.y0 + (i + 0.5) * rowH;

      // value scale: asinh-compressed strength, bull half above the split, bear half below
      // lines trace each stock's price path in ADR units (smooth); rank still decides the column row
      const hist = S.hist && S.hist.t0 === b.t0 ? (S.hist.path || S.hist.bars) : {};
      const cur = x => (x.adr ? x.mv / x.adr : x.sc);
      const pos = [], neg = [];
      for (const x of b.stocks) {
        for (const v of [...(hist[x.s] || []), cur(x)]) { if (v > 0) pos.push(v); else if (v < 0) neg.push(-v); }
      }
      const q = (a, p) => { if (!a.length) return 1; a.sort((m, k) => m - k); return a[Math.min(a.length - 1, Math.floor(p * a.length))] || 1; };
      const K = 0.2, mp = Math.asinh(q(pos, 1) * 1.04 / K), mn = Math.asinh(q(neg, 1) * 1.04 / K);
      const pad = 6;
      const yv = v => v >= 0
        ? Math.max(g.y0 + 2, yz - Math.min(1, Math.asinh(v / K) / mp) * (yz - g.y0 - pad))
        : Math.min(g.y1 - 2, yz + Math.min(1, Math.asinh(-v / K) / mn) * (g.y1 - yz - pad));
      this.yv = yv;

      // panel + side tint
      o.fillStyle = C.plot; o.fillRect(L, T, W, Hh);
      const tb = o.createLinearGradient(0, g.y0, 0, yz);
      tb.addColorStop(0, A(C.bullRgb, 0.07)); tb.addColorStop(1, A(C.bullRgb, 0));
      o.fillStyle = tb; o.fillRect(g.x0, g.y0, g.x1 - g.x0, yz - g.y0);
      const tr = o.createLinearGradient(0, yz, 0, g.y1);
      tr.addColorStop(0, A(C.bearRgb, 0)); tr.addColorStop(1, A(C.bearRgb, 0.07));
      o.fillStyle = tr; o.fillRect(g.x0, yz, g.x1 - g.x0, g.y1 - yz);
      o.strokeStyle = C.grid; o.lineWidth = 1; o.strokeRect(L + 0.5, T + 0.5, W - 1, Hh - 1);
      // faint horizontal guides at half of each side
      o.setLineDash([2, 6]); o.strokeStyle = C.grid;
      for (const y of [(g.y0 + yz) / 2, (yz + g.y1) / 2]) { o.beginPath(); o.moveTo(g.x0, y); o.lineTo(g.xf, y); o.stroke(); }
      o.setLineDash([]);
      // opening 15 minutes
      o.fillStyle = A('61,123,255', 0.07); o.fillRect(X(b.t0), g.y0, Math.max(2, X(b.t0 + 900) - X(b.t0)), H);
      // hour guides + labels
      o.font = '500 9px JetBrains Mono, monospace'; o.textAlign = 'center'; o.fillStyle = C.muted;
      o.setLineDash([2, 4]);
      for (let t = b.t0 + 2700; t < now; t += 3600) {
        const x = X(t); o.strokeStyle = C.grid; o.beginPath(); o.moveTo(x, g.y0); o.lineTo(x, g.y1); o.stroke();
        if (g.xf - x > 34) o.fillText(hhmm(t), x, g.y1 + 14);
      }
      o.strokeStyle = A(C.ink, 0.25); o.beginPath(); o.moveTo(g.xf, g.y0); o.lineTo(g.xf, g.y1); o.stroke();
      o.setLineDash([]);
      o.fillStyle = C.strong; o.font = '700 9.5px JetBrains Mono, monospace'; o.fillText(hhmm(b.status.now), g.xf, g.y1 + 14);
      // split line + side rail (no axis numbers)
      o.strokeStyle = A(C.ink, 0.28); o.setLineDash([4, 4]);
      o.beginPath(); o.moveTo(g.axisX, yz); o.lineTo(g.right - 4, yz); o.stroke(); o.setLineDash([]);
      o.fillStyle = C.bull; o.fillRect(g.axisX, g.y0, 2, yz - g.y0);
      o.fillStyle = C.bear; o.fillRect(g.axisX, yz, 2, g.y1 - yz);

      // stock lines: smooth curve from the open to now, then a bend into the stock's rank row
      const boardSet = new Set([...b.boards.bull, ...b.boards.bear]);
      const pickSet = new Set([...b.picks.bull, ...b.picks.bear]);
      const rankIdx = new Map(b.stocks.map((x, i) => [x.s, i]));
      const pathOf = x => {
        const pts = [[X(b.t0), yz]];
        (hist[x.s] || []).forEach((v, k) => { if (v != null) pts.push([X(b.t0 + (k + 1) * 300), yv(v)]); });
        pts.push([X(now), yv(cur(x))]);
        return pts;
      };
      const trace = (pts, endY) => {
        o.beginPath(); o.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length - 1; i++) {
          const mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
          o.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
        }
        const last = pts[pts.length - 1];
        o.lineTo(last[0], last[1]);
        if (endY != null) {
          const mx = (last[0] + g.colX) / 2;
          o.bezierCurveTo(mx, last[1], mx, endY, g.colX - 2, endY);
        }
        o.stroke();
      };
      const hl = S.hlSector;
      const inHl = x => hl && (hl === 'NIFTY_50' ? x.n50 : x.sec === hl);
      o.lineJoin = 'round'; o.lineCap = 'round';
      // background crowd: additive blending in dark mode gives the x-ray density glow
      o.globalCompositeOperation = theme() === 'dark' ? 'lighter' : 'source-over';
      for (const x of b.stocks) {
        if (boardSet.has(x.s) || inHl(x)) continue;
        o.strokeStyle = A(sideRgb(x), hl ? 0.03 : (theme() === 'dark' ? 0.11 : C.dim));
        o.lineWidth = 0.9; trace(pathOf(x), rowY(rankIdx.get(x.s)));
      }
      o.globalCompositeOperation = 'source-over';
      const front = b.stocks.filter(x => boardSet.has(x.s) || inHl(x));
      front.sort((a, c) => (pickSet.has(a.s) ? 1 : 0) - (pickSet.has(c.s) ? 1 : 0)); // picks on top
      for (const x of front) {
        const pk = pickSet.has(x.s), isHl = inHl(x) && !boardSet.has(x.s);
        const pts = pathOf(x), endY = rowY(rankIdx.get(x.s));
        o.globalAlpha = hl && !inHl(x) ? 0.25 : 1;
        // soft halo, then the crisp line
        o.strokeStyle = A(isHl ? C.ink : sideRgb(x), pk ? 0.22 : 0.12);
        o.lineWidth = pk ? 6 : 4; trace(pts, endY);
        o.strokeStyle = isHl ? A(C.ink, 0.8) : side(x);
        o.lineWidth = pk ? 1.9 : 1.2; o.shadowColor = side(x); o.shadowBlur = (pk ? 10 : 4) * C.glow;
        trace(pts, endY); o.shadowBlur = 0;
      }
      o.globalAlpha = 1;
      // NIFTY 50 basket average (index reference)
      const n50 = b.stocks.filter(x => x.n50);
      if (n50.length) {
        const k = Math.max(0, ...n50.map(x => (hist[x.s] || []).length));
        const pts = [[X(b.t0), yz]];
        for (let i = 0; i < k; i++) {
          const vals = n50.map(x => (hist[x.s] || [])[i]).filter(v => v != null);
          if (vals.length) pts.push([X(b.t0 + (i + 1) * 300), yv(vals.reduce((a, c) => a + c, 0) / vals.length)]);
        }
        pts.push([X(now), yv(n50.reduce((a, x) => a + cur(x), 0) / n50.length)]);
        o.strokeStyle = A('61,123,255', 0.2); o.lineWidth = 5; trace(pts, null);
        o.strokeStyle = C.blue; o.lineWidth = 1.7; o.shadowColor = C.blue; o.shadowBlur = 8 * C.glow; trace(pts, null); o.shadowBlur = 0;
        const e = pts[pts.length - 1];
        o.fillStyle = C.blue; o.textAlign = 'right'; o.font = '700 9px JetBrains Mono, monospace';
        o.fillText('NIFTY 50', e[0] - 6, e[1] - 6);
        o.beginPath(); o.arc(e[0], e[1], 2.5, 0, 7); o.fill();
      }
      // ranked column
      const maxAbs = Math.max(1e-6, ...b.stocks.map(x => Math.abs(x.sc)));
      o.fillStyle = A(C.ink, 0.04); o.fillRect(g.colX - 2, g.y0, g.colW + 4, H);
      b.stocks.forEach((x, i) => {
        const y = g.y0 + i * rowH, onB = boardSet.has(x.s);
        o.fillStyle = side(x); o.globalAlpha = onB ? 1 : 0.35;
        o.fillRect(g.colX, y, Math.max(1.5, Math.abs(x.sc) / maxAbs * g.colW), Math.max(0.8, rowH - 0.4));
      });
      o.globalAlpha = 1;
      const nb = b.boards.bull.length, nr = b.boards.bear.length;
      o.lineWidth = 1;
      if (nb) { o.strokeStyle = C.bull; o.shadowColor = C.bull; o.shadowBlur = 8 * C.glow; o.strokeRect(g.colX - 3.5, g.y0 - 0.5, g.colW + 7, nb * rowH + 1); }
      if (nr) { o.strokeStyle = C.bear; o.shadowColor = C.bear; o.strokeRect(g.colX - 3.5, g.y1 - nr * rowH - 0.5, g.colW + 7, nr * rowH + 1); }
      o.shadowBlur = 0;
      o.fillStyle = C.muted; o.textAlign = 'center'; o.font = '600 8.5px JetBrains Mono, monospace';
      o.fillText(String(n), g.colX + g.colW / 2, g.y0 - 6);
      // flow links: column rows -> tiles -> pick cards
      this.links = [];
      const stageRect = sr;
      const rel = el => { const r = el.getBoundingClientRect(); return { l: r.left - stageRect.left, t: r.top - stageRect.top, w: r.width, h: r.height }; };
      const tilesRight = rel($('#tilesBull')).l > g.right;
      if (tilesRight) {
        for (const sd of ['bull', 'bear']) {
          const tiles = sd === 'bull' ? $('#tilesBull') : $('#tilesBear');
          const cards = sd === 'bull' ? $('#cardsBull') : $('#cardsBear');
          b.boards[sd].forEach((sym, k) => {
            const i = sd === 'bull' ? k : n - 1 - k;
            const tile = tiles.querySelector(`.tile[data-rank="${k + 1}"]`); if (!tile) return;
            const r = rel(tile);
            const p0 = [g.colX + g.colW + 3, g.y0 + (i + 0.5) * rowH], p3 = [r.l, r.t + r.h / 2];
            const dx = (p3[0] - p0[0]) * 0.5;
            this.links.push({ p: [p0, [p0[0] + dx, p0[1]], [p3[0] - dx, p3[1]], p3], col: sd === 'bull' ? C.bull : C.bear, w: k < 3 ? 1.6 : 0.9, sp: 0.18 + (k % 3) * 0.04, ph: k * 0.37 });
          });
          b.picks[sd].forEach((sym, j) => {
            const tile = tiles.querySelector(`.tile[data-s="${CSS.escape(sym)}"]`), card = cards.children[j];
            if (!tile || !card) return;
            const a = rel(tile), c = rel(card);
            const p0 = [a.l + a.w, a.t + a.h / 2], p3 = [c.l, c.t + c.h / 2], dx = (p3[0] - p0[0]) * 0.5;
            this.links.push({ p: [p0, [p0[0] + dx, p0[1]], [p3[0] - dx, p3[1]], p3], col: sd === 'bull' ? C.bull : C.bear, w: 2.2, sp: 0.35, ph: j * 0.3, card: true });
          });
        }
      }
      for (const lk of this.links) {
        const [p0, p1, p2, p3] = lk.p;
        const gr = o.createLinearGradient(p0[0], 0, p3[0], 0);
        gr.addColorStop(0, lk.col + '22'); gr.addColorStop(0.5, lk.col + (lk.card ? 'cc' : '88')); gr.addColorStop(1, lk.col + 'ee');
        o.strokeStyle = gr; o.lineWidth = lk.w; o.shadowColor = lk.col; o.shadowBlur = (lk.card ? 12 : 4) * C.glow;
        o.beginPath(); o.moveTo(...p0); o.bezierCurveTo(...p1, ...p2, ...p3); o.stroke();
      }
      o.shadowBlur = 0;
      this.ends = b.stocks.filter(x => pickSet.has(x.s)).map(x => ({ x: X(now), y: yv(cur(x)), col: side(x) }));
    },
    frame(ts) {
      requestAnimationFrame(t => this.frame(t));
      const g = this.geom; if (!g || !this.cv.width) return;
      const ctx = this.cv.getContext('2d');
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, this.cv.width, this.cv.height);
      ctx.drawImage(this.off, 0, 0);
      const dpr = this.cv.width / this.cv.clientWidth; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const s = ts / 1000;
      // x-ray sweep across the plot
      const span = g.xf - g.x0, sx = g.x0 + ((s / 6) % 1) * span;
      const gr = ctx.createLinearGradient(sx - 60, 0, sx, 0);
      gr.addColorStop(0, A(C.sweep, 0)); gr.addColorStop(1, A(C.sweep, 0.10));
      ctx.fillStyle = gr; ctx.fillRect(sx - 60, g.y0, 60, g.y1 - g.y0);
      ctx.fillStyle = A(C.sweep, 0.4); ctx.fillRect(sx, g.y0, 1, g.y1 - g.y0);
      // particles on flow links
      for (const lk of this.links) {
        for (let q = 0; q < (lk.card ? 3 : 2); q++) {
          const u = (s * lk.sp + lk.ph + q / (lk.card ? 3 : 2)) % 1;
          const [x, y] = bez(lk.p, u);
          ctx.fillStyle = C.dot || lk.col; ctx.shadowColor = lk.col; ctx.shadowBlur = 10 * C.glow;
          ctx.beginPath(); ctx.arc(x, y, lk.card ? 2 : 1.4, 0, 7); ctx.fill();
        }
      }
      ctx.shadowBlur = 0;
      // pulsing ends of pick lines
      const r = 3 + 3 * ((s * 0.9) % 1);
      for (const e of this.ends || []) {
        ctx.strokeStyle = e.col; ctx.globalAlpha = 1 - ((s * 0.9) % 1); ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(e.x, e.y, r, 0, 7); ctx.stroke(); ctx.globalAlpha = 1;
        ctx.fillStyle = C.dot || e.col; ctx.beginPath(); ctx.arc(e.x, e.y, 2, 0, 7); ctx.fill();
      }
    },
  };
  function bez(p, u) {
    const v = 1 - u, a = v * v * v, b = 3 * v * v * u, c = 3 * v * u * u, d = u * u * u;
    return [a * p[0][0] + b * p[1][0] + c * p[2][0] + d * p[3][0], a * p[0][1] + b * p[1][1] + c * p[2][1] + d * p[3][1]];
  }

  // ----------------------------------------------------------------- market picture strip
  const pulse = {
    draw() {
      const b = S.board, cv = $('#pulse'); if (!b) return;
      const { ctx, w, h } = fitCanvas(cv);
      ctx.clearRect(0, 0, w, h);
      const padL = 96, padR = 96, mid = h / 2 + 4;
      const m = Math.max(1, Math.ceil(Math.max(...b.stocks.map(x => Math.abs(x.chg)))));
      const X = v => padL + (v + m) / (2 * m) * (w - padL - padR);
      ctx.strokeStyle = A(C.ink, 0.2); ctx.beginPath(); ctx.moveTo(padL, mid); ctx.lineTo(w - padR, mid); ctx.stroke();
      ctx.font = '500 8px JetBrains Mono, monospace'; ctx.textAlign = 'center'; ctx.fillStyle = C.muted;
      for (let v = -m; v <= m; v += Math.max(1, Math.round(m / 3))) { ctx.fillRect(X(v), mid - 2, 1, 4); ctx.fillText((v > 0 ? '+' : '') + v + '%', X(v), h - 1); }
      const board = new Set([...b.boards.bull, ...b.boards.bear]), picks = new Set([...b.picks.bull, ...b.picks.bear]);
      const stack = {};
      const order = [...b.stocks].sort((a, c) => Math.abs(a.sc) - Math.abs(c.sc));
      for (const x of order) {
        const bx = Math.round(X(x.chg) / 4), key = x.side + bx, k = (stack[key] = (stack[key] || 0) + 1);
        const y = x.side === 'bull' ? mid - 4 - (k - 1) * 3.2 : mid + 4 + (k - 1) * 3.2;
        if (y < 2 || y > h - 10) continue;
        const cx = X(x.chg), col = x.ev ? C.amber : side(x), on = board.has(x.s);
        ctx.fillStyle = col; ctx.globalAlpha = on ? 1 : 0.5; ctx.shadowColor = col; ctx.shadowBlur = on ? 8 * C.glow : 0;
        ctx.beginPath(); ctx.arc(cx, y, on ? 2.2 : 1.4, 0, 7); ctx.fill();
        if (picks.has(x.s)) { ctx.strokeStyle = C.strong; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, y, 4.2, 0, 7); ctx.stroke(); }
      }
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
      const tag = (s, x, align) => {
        if (!s) return;
        ctx.textAlign = align; ctx.font = '700 9px Inter Tight, sans-serif';
        ctx.fillStyle = s.chg >= 0 ? C.bull : C.bear; ctx.fillText(s.name, x, mid - 3);
        ctx.font = '600 9px JetBrains Mono, monospace'; ctx.fillText(pct(s.chg), x, mid + 9);
      };
      tag(b.lag, 4, 'left'); tag(b.lead, w - 4, 'right');
    },
  };

  // ----------------------------------------------------------------- popup chart
  async function getChart(sym, maxAge = 4000) {
    const c = S.charts[sym];
    if (c && Date.now() - c.at < maxAge) return c.data;
    const r = await fetch('/api/chart/' + encodeURIComponent(sym), { cache: 'no-store' });
    if (!r.ok) throw new Error('chart ' + r.status);
    const data = await r.json();
    S.charts[sym] = { at: Date.now(), data };
    return data;
  }
  let hoverTimer = null, hideTimer = null;
  function schedulePop(sym, el) {
    clearTimeout(hideTimer); clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => openPop(sym, el, false), 120);
  }
  function scheduleHide() {
    clearTimeout(hoverTimer);
    if (S.pop && S.pop.pinned) return;
    hideTimer = setTimeout(closePop, 220);
  }
  function closePop() { $('#pop').hidden = true; S.pop = null; }
  async function openPop(sym, anchor, pinned) {
    S.pop = { sym, anchor, pinned };
    try { renderPop(await getChart(sym, pinned ? 0 : 4000)); } catch (e) { /* not ready */ }
  }
  async function refreshPop() {
    const p = S.pop; if (!p) return;
    try { const d = await getChart(p.sym); if (S.pop && S.pop.sym === p.sym) renderPop(d); } catch (e) { /* ignore */ }
  }
  function renderPop(d) {
    const p = S.pop; if (!p) return;
    const x = S.by[d.stock.s] || d.stock, s = d.setup, el = $('#pop'), isB = x.side === 'bull';
    el.className = 'pop ' + x.side + (p.pinned ? ' pinned' : '');
    const L = s ? s.labels : { stop: isB ? 'S1' : 'R1', t1: isB ? 'R1' : 'S1', t2: isB ? 'R2' : 'S2' };
    const row = (k, v, cls = '') => `<div><small>${k}</small><span class="${cls}">${v}</span></div>`;
    el.innerHTML = `<button class="p-close" aria-label="Close">×</button>
      <div class="p-head"><span class="mono-logo" style="background:linear-gradient(135deg,hsl(${hue(x.s)} 70% 50%),hsl(${hue(x.s)} 70% 30%))">${esc(initials(x.s))}</span>
        <div><b>${esc(x.s)}</b><small>${esc(x.s)} · ${esc(x.secName)}</small></div><canvas class="p-spark"></canvas></div>
      <div class="p-px"><b>₹${px(x.ltp)}</b><span class="${x.chg >= 0 ? 'up' : 'dn'}">${pct(x.chg)} · ${sgn(x.chgAbs)}</span></div>
      <div class="p-grid">
        ${row('RANK', `p${x.p.toFixed(1)} · #${x.r}/${x.sideN}`)}
        ${row('CONV', `${x.cv} <span class="${isB ? 'up' : 'dn'}">${dots(x.cv)}</span>`)}
        ${row('OI', `${pct(x.oiChg, 1)} · ${esc(x.bu || '–')}`)}
        ${row('ΔOI', `${big(x.oiAbs)} · ${x.av == null ? '–' : x.av ? '▲ above VWAP' : '▼ below VWAP'}`)}
        ${row('VWAP', px(x.vw))}
        ${row('OB', s ? `${px(s.ob.lo)}–${px(s.ob.hi)}` : '–')}
        ${row(`Z/${L.stop}`, s ? `${px(s.z)} · <span class="hl">${px(s.stop)}</span>` : '–')}
        ${row(`${L.t1}/${L.t2}`, s ? `${px(s.t1)} · ${px(s.t2)}` : '–')}
        ${row('R:R', s && s.rr != null ? '1:' + s.rr.toFixed(1) : '–')}
        ${row('RULE', esc(x.rule || '–'), (x.rule || '').startsWith('PICK') ? (isB ? 'up' : 'dn') : '')}
      </div>
      <canvas class="p-chart"></canvas>`;
    $('.p-close', el).onclick = closePop;
    el.hidden = false;
    position(el, p.anchor);
    drawSpark($('.p-spark', el), d.candles.map(c => c[4]), side(x));
    drawChart($('.p-chart', el), d, x);
  }
  function position(el, anchor) {
    if (window.innerWidth <= 1100) return; // CSS bottom sheet
    const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let left, top;
    if (anchor) {
      const r = anchor.getBoundingClientRect();
      left = r.left - w - 12 >= 8 ? r.left - w - 12 : Math.min(vw - w - 8, r.right + 12);
      top = r.top + r.height / 2 - h / 2;
    } else { left = (vw - w) / 2; top = (vh - h) / 2; }
    el.style.left = Math.max(8, left) + 'px';
    el.style.top = Math.max(8, Math.min(vh - h - 8, top)) + 'px';
  }
  function drawSpark(cv, arr, col) {
    const { ctx, w, h } = fitCanvas(cv);
    if (arr.length < 2) return;
    const lo = Math.min(...arr), hi = Math.max(...arr) + 1e-9;
    ctx.beginPath(); arr.forEach((v, i) => { const X = i / (arr.length - 1) * w, Y = h - 2 - (v - lo) / (hi - lo) * (h - 4); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.strokeStyle = col; ctx.lineWidth = 1.3; ctx.stroke();
  }
  function drawChart(cv, d, x) {
    const { ctx, w, h } = fitCanvas(cv);
    ctx.clearRect(0, 0, w, h);
    const cs = d.candles, n = cs.length, s = d.setup;
    if (!n) { ctx.fillStyle = C.muted; ctx.fillText('No candles yet', 10, 20); return; }
    const padL = 6, padR = 86, padT = 12, padB = 20;
    const slots = Math.max(n + 3, 20);
    const cw = (w - padL - padR) / slots;
    const idx = t => Math.round((t - cs[0][0]) / 300);
    const Xi = i => padL + (i + 0.5) * cw;
    let lo = Math.min(...cs.map(c => c[3])), hi = Math.max(...cs.map(c => c[2]));
    const lv = s ? [s.stop, s.t1, s.t2, ...s.extras].filter(v => v != null) : [];
    const span0 = hi - lo || hi * 0.01;
    for (const v of lv) { if (v < lo && lo - v < span0 * 0.8) lo = v; if (v > hi && v - hi < span0 * 0.8) hi = v; }
    const pad = (hi - lo) * 0.05; lo -= pad; hi += pad;
    const Y = v => padT + (hi - v) / (hi - lo) * (h - padT - padB);
    const R = w - padR;
    // grid + hour labels
    ctx.font = '500 9px JetBrains Mono, monospace'; ctx.fillStyle = C.muted; ctx.textAlign = 'center';
    cs.forEach((c, i) => {
      const m = new Date(c[0] * 1000); const ist = (m.getUTCHours() * 60 + m.getUTCMinutes() + 330) % 1440;
      if (ist % 60 === 0) {
        ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(Xi(i), padT); ctx.lineTo(Xi(i), h - padB); ctx.stroke();
        ctx.fillText(hhmm(c[0]), Xi(i), h - 5);
      }
    });
    // earlier setups (each over its own part of the day)
    const cur = s && s.ob;
    for (const ob of d.obs) {
      const isCur = cur && ob.t0 === cur.t0 && ob.dir === s.dir;
      if (isCur) continue;
      const i0 = idx(ob.t0), i1 = ob.until ? idx(ob.until) : n - 1;
      if (Y(ob.hi) > h || Y(ob.lo) < 0) continue;
      const orgb = ob.dir === 'bull' ? C.bullRgb : C.bearRgb;
      ctx.fillStyle = A(orgb, 0.10);
      ctx.strokeStyle = A(orgb, 0.38);
      const xa = Xi(i0) - cw / 2, xb = Xi(i1) + cw / 2;
      ctx.fillRect(xa, Y(ob.hi), xb - xa, Math.max(1, Y(ob.lo) - Y(ob.hi)));
      ctx.strokeRect(xa + 0.5, Y(ob.hi) + 0.5, xb - xa - 1, Math.max(1, Y(ob.lo) - Y(ob.hi)) - 1);
    }
    // area under price
    const col = side(x);
    const grad = ctx.createLinearGradient(0, padT, 0, h - padB);
    grad.addColorStop(0, A(sideRgb(x), 0.28)); grad.addColorStop(1, A(sideRgb(x), 0));
    ctx.beginPath(); ctx.moveTo(Xi(0), h - padB); cs.forEach((c, i) => ctx.lineTo(Xi(i), Y(c[4]))); ctx.lineTo(Xi(n - 1), h - padB); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    // current block + zone band
    if (s) {
      const i0 = idx(cur.t0), xa = Xi(i0) - cw / 2;
      const srgb = s.dir === 'bull' ? C.bullRgb : C.bearRgb;
      ctx.fillStyle = A(srgb, 0.30);
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.fillRect(xa, Y(cur.hi), Xi(idx(cur.t1)) + cw / 2 - xa, Math.max(1.5, Y(cur.lo) - Y(cur.hi)));
      ctx.strokeRect(xa + 0.5, Y(cur.hi) + 0.5, Xi(idx(cur.t1)) + cw / 2 - xa - 1, Math.max(1.5, Y(cur.lo) - Y(cur.hi)) - 1);
      ctx.fillStyle = A(srgb, 0.16);
      const zt = Y(Math.max(...s.zone)), zb = Y(Math.min(...s.zone));
      ctx.fillRect(xa, Math.min(zt, Y(cur.hi)), R - xa, Math.max(zb, Y(cur.lo)) - Math.min(zt, Y(cur.hi)));
    }
    // VWAP
    ctx.strokeStyle = C.blue; ctx.lineWidth = 1.2; ctx.setLineDash([4, 3]); ctx.beginPath();
    let started = false;
    d.vwap.forEach((v, i) => { if (v == null) return; started ? ctx.lineTo(Xi(i), Y(v)) : ctx.moveTo(Xi(i), Y(v)); started = true; });
    ctx.stroke(); ctx.setLineDash([]);
    // candles
    const bw = Math.max(2.5, Math.min(14, cw * 0.72));
    cs.forEach(([, o, hh, l, c], i) => {
      const up = c >= o, cx = Xi(i);
      ctx.strokeStyle = ctx.fillStyle = up ? (x.side === 'bull' ? C.candleUp : C.candleUp2) : C.candleDn;
      if (i >= d.closedN) ctx.globalAlpha = 0.6; // forming bar
      ctx.beginPath(); ctx.moveTo(cx, Y(hh)); ctx.lineTo(cx, Y(l)); ctx.lineWidth = bw > 6 ? 1.5 : 1; ctx.stroke();
      ctx.fillRect(cx - bw / 2, Y(Math.max(o, c)), bw, Math.max(1, Math.abs(Y(o) - Y(c))));
      ctx.globalAlpha = 1;
    });
    // levels with right-side labels
    const labels = [];
    const level = (v, color, text, dash, fromX) => {
      if (v == null || v < lo || v > hi) return;
      const y = Y(v);
      ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash(dash || []);
      ctx.beginPath(); ctx.moveTo(fromX, y); ctx.lineTo(R, y); ctx.stroke(); ctx.setLineDash([]);
      labels.push({ y, color, text });
    };
    if (s) {
      const fx = Xi(idx(cur.t0)) - cw / 2;
      s.extras.forEach((v, i) => level(v, C.amber, `${s.labels.extras[i]} ${px(v)}`, [2, 3], padL));
      level(s.t2, A(C.ink, 0.85), `${s.labels.t2} ${px(s.t2)}`, s.proj[1] ? [5, 3] : null, fx);
      level(s.t1, A(C.ink, 0.85), `${s.labels.t1} ${px(s.t1)}`, s.proj[0] ? [5, 3] : null, fx);
      level(s.z, col, `Z ${px(s.z)}`, null, fx);
      level(s.stop, C.yellow, `${s.labels.stop} ${px(s.stop)}`, null, fx);
    }
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) labels[i].ly = Math.max(labels[i].y, (labels[i - 1].ly ?? labels[i - 1].y) + 13);
    ctx.font = '600 10px JetBrains Mono, monospace'; ctx.textAlign = 'left';
    for (const lb of labels) {
      const y = lb.ly ?? lb.y, tw = ctx.measureText(lb.text).width;
      ctx.fillStyle = A(C.shade, 0.8); ctx.fillRect(R + 3, y - 7, tw + 6, 13);
      ctx.fillStyle = lb.color; ctx.fillText(lb.text, R + 6, y + 3);
    }
    // last price
    const ly = Y(cs[n - 1][4]), lx = Xi(n - 1);
    ctx.fillStyle = C.dot || col; ctx.shadowColor = col; ctx.shadowBlur = 10 * C.glow;
    ctx.beginPath(); ctx.arc(lx, ly, 3, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.strokeStyle = A(C.ink, 0.6); ctx.beginPath(); ctx.arc(lx, ly, 6, 0, 7); ctx.stroke();
  }

  // ----------------------------------------------------------------- interactions
  function syncThemeButton() {
    const next = theme() === 'light' ? 'dark' : 'light', btn = $('#theme');
    btn.setAttribute('aria-label', `Switch to ${next} mode`);
    btn.title = `Switch to ${next} mode`;
  }
  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('xray:theme', t); } catch (e) { /* private mode */ }
    C = THEMES[t];
    syncThemeButton();
    if (S.board) { onBoard(S.board); if (S.pop) refreshPop(); }
  }

  function bindInteractions() {
    const stage = $('#stage'), pop = $('#pop');
    syncThemeButton();
    $('#theme').addEventListener('click', () => setTheme(theme() === 'light' ? 'dark' : 'light'));
    const hit = e => e.target.closest('.tile[data-s], .card[data-s]');
    stage.addEventListener('mouseover', e => { const t = hit(e); if (t && window.innerWidth > 1100) schedulePop(t.dataset.s, t); });
    stage.addEventListener('mouseout', e => { const t = hit(e); if (t && !t.contains(e.relatedTarget)) scheduleHide(); });
    stage.addEventListener('click', e => { const t = hit(e); if (t) { clearTimeout(hoverTimer); openPop(t.dataset.s, t, true); } });
    pop.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    pop.addEventListener('mouseleave', scheduleHide);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') { closePop(); $('#qres').hidden = true; }
      if (e.key === '/' && document.activeElement !== $('#q')) { e.preventDefault(); $('#q').focus(); }
    });
    document.addEventListener('click', e => {
      if (S.pop && S.pop.pinned && !pop.contains(e.target) && !hit(e) && !e.target.closest('.search')) closePop();
    });
    // search
    const q = $('#q'), res = $('#qres');
    let sel = 0, items = [];
    const show = () => {
      const v = q.value.trim().toUpperCase();
      items = v && S.board ? S.board.stocks.filter(x => x.s.includes(v)).sort((a, b) => a.s.indexOf(v) - b.s.indexOf(v)).slice(0, 8) : [];
      sel = 0;
      res.hidden = !items.length;
      res.innerHTML = items.map((x, i) => `<li role="option" aria-selected="${i === sel}" data-s="${esc(x.s)}"><span>${esc(x.s)} <small style="color:#6b7f77">${esc(x.secName)}</small></span><span class="${x.chg >= 0 ? 'up' : 'dn'}">${pct(x.chg)}</span></li>`).join('');
    };
    const pick = sym => { res.hidden = true; q.value = ''; q.blur(); openPop(sym, null, true); };
    q.addEventListener('input', show);
    q.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % Math.max(1, items.length);
        [...res.children].forEach((li, i) => li.setAttribute('aria-selected', i === sel));
      } else if (e.key === 'Enter' && items[sel]) pick(items[sel].s);
    });
    res.addEventListener('click', e => { const li = e.target.closest('li'); if (li) pick(li.dataset.s); });
    let rz;
    window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => { if (S.board) onBoard(S.board); }, 120); });
  }

  xray.init();
  bindInteractions();
  poll();
})();
