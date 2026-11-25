window.BSF = (() => {
  const ANG = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315};
  const angdiff = (a, b) => { let d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
  const u16 = (b, o) => b[o] | (b[o + 1] << 8);
  const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
  async function rng(url, a, b) {
    const r = await fetch(url, {headers: {Range: b == null ? `bytes=${a}` : `bytes=${a}-${b}`}});
    if (!r.ok) throw new Error('http ' + r.status);
    return {status: r.status, buf: new Uint8Array(await r.arrayBuffer())};
  }
  async function inflate(data, method) {
    if (method === 0) return data;
    const ds = new DecompressionStream('deflate-raw');
    const s = new Blob([data]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(s).arrayBuffer());
  }
  async function openZip(url) {
    let t = await rng(url, -65536);
    let full = t.status === 200 ? t.buf : null;
    let tail = t.buf, e = -1;
    for (let i = tail.length - 22; i >= 0; i--) if (u32(tail, i) === 0x06054b50) { e = i; break; }
    if (e < 0) throw new Error('no eocd');
    const cdSize = u32(tail, e + 12), cdOff = u32(tail, e + 16);
    const tailStart = full ? 0 : cdOff + cdSize - e;
    let cd;
    if (cdOff >= tailStart) cd = tail.subarray(cdOff - tailStart, cdOff - tailStart + cdSize);
    else cd = (await rng(url, cdOff, cdOff + cdSize - 1)).buf;
    const ents = {};
    for (let p = 0; p + 46 <= cd.length && u32(cd, p) === 0x02014b50;) {
      const meth = u16(cd, p + 10), csz = u32(cd, p + 20), nl = u16(cd, p + 28), xl = u16(cd, p + 30), cl = u16(cd, p + 32), lo = u32(cd, p + 42);
      const name = new TextDecoder().decode(cd.subarray(p + 46, p + 46 + nl));
      ents[name.toLowerCase().split('/').pop()] = {meth, csz, lo, nl};
      p += 46 + nl + xl + cl;
    }
    async function read(name) {
      const en = ents[name.toLowerCase()];
      if (!en) return null;
      let b;
      if (full) b = full.subarray(en.lo, en.lo + 30 + en.nl + 4096 + en.csz);
      else b = (await rng(url, en.lo, en.lo + 30 + en.nl + 4096 + en.csz)).buf;
      const nl = u16(b, 26), xl = u16(b, 28), s = 30 + nl + xl;
      const out = await inflate(b.subarray(s, s + en.csz), en.meth);
      return new TextDecoder().decode(out);
    }
    return {read, names: Object.keys(ents)};
  }
  function parse(dat) {
    const j = JSON.parse(dat); const notes = [], bombs = []; let chains = 0, arcs = 0;
    if (j._notes) {
      for (const n of j._notes) { if (n._type === 0 || n._type === 1) notes.push([n._time, n._lineIndex, n._lineLayer, n._type, n._cutDirection]); else if (n._type === 3) bombs.push([n._time]); }
      arcs = (j._sliders || []).length;
    } else if (j.colorNotes && j.colorNotes.length && ('b' in j.colorNotes[0] || 'x' in j.colorNotes[0] || 'c' in j.colorNotes[0]) && !j.colorNotesData) {
      for (const n of j.colorNotes) notes.push([n.b || 0, n.x || 0, n.y || 0, n.c || 0, n.d || 0]);
      for (const b of j.bombNotes || []) bombs.push([b.b || 0]);
      chains = (j.burstSliders || []).length; arcs = (j.sliders || []).length;
    } else if (j.colorNotes) {
      const D = j.colorNotesData || [];
      for (const n of j.colorNotes) { const d = D[n.i || 0] || {}; notes.push([n.b || 0, d.x || 0, d.y || 0, d.c || 0, d.d || 0]); }
      for (const b of j.bombNotes || []) bombs.push([b.b || 0]);
      chains = (j.chains || []).length; arcs = (j.arcs || []).length;
    }
    notes.sort((a, b) => a[0] - b[0] || a[3] - b[3]);
    return {notes, bombs, chains, arcs};
  }
  function info(txt, ch, df) {
    const i = JSON.parse(txt);
    let bpm = i._beatsPerMinute || (i.audio || {}).bpm || 120, njs = null, off = null, file = null;
    if (i._difficultyBeatmapSets) {
      for (const s of i._difficultyBeatmapSets) if (s._beatmapCharacteristicName === ch)
        for (const b of s._difficultyBeatmaps) if (b._difficulty === df) { njs = b._noteJumpMovementSpeed; off = b._noteJumpStartBeatOffset; file = b._beatmapFilename; }
    } else {
      for (const b of i.difficultyBeatmaps || []) if (b.characteristic === ch && b.difficulty === df) {
        njs = (b.noteJumpMovementSpeed ?? (b.beatmapAuthors ? null : null)); off = b.noteJumpStartBeatOffset; file = b.beatmapDataFilename;
      }
    }
    return {bpm: +bpm, njs, off, file};
  }
  function feat(dat, inf) {
    const {notes, bombs, chains, arcs} = parse(dat);
    if (notes.length < 10) return null;
    const sec = b => b * 60 / inf.bpm;
    const dur = Math.max(sec(notes[notes.length - 1][0]) - sec(notes[0][0]), 1e-6);
    const N = notes.length;
    const sw = {0: [], 1: []};
    for (const c of [0, 1]) {
      const h = notes.filter(n => n[3] === c);
      for (let i = 0; i < h.length;) { const g = [h[i]]; while (i + 1 < h.length && h[i + 1][0] - g[0][0] < 0.0626) { i++; g.push(h[i]); } sw[c].push(g); i++; }
    }
    let gaps = 0, fastRev = 0, fast = 0;
    for (const c of [0, 1]) {
      const s = sw[c];
      for (let k = 0; k + 1 < s.length; k++) {
        const a = s[k], b = s[k + 1], g = sec(b[0][0]) - sec(a[0][0]);
        if (g <= 0) continue; gaps++;
        if (g < 0.25) fast++;
        const da = (a.find(n => ANG[n[4]] != null) || [])[4], db = (b.find(n => ANG[n[4]] != null) || [])[4];
        if (da != null && db != null && g < 0.3 && angdiff(ANG[da], ANG[db]) >= 135) fastRev++;
      }
    }
    const cnt = {}; for (const n of notes) { const k = Math.round(n[0] * 100) / 100 + '|' + n[3]; cnt[k] = (cnt[k] || 0) + 1; }
    const sbsc = Object.values(cnt).filter(v => v >= 2).reduce((a, v) => a + v, 0) / N;
    const r = x => Math.round(x * 1000) / 1000;
    return {
      nps: r(N / dur), sps: r((gaps + 2) / dur), play: Math.round(dur), notes: N, njs: inf.njs, chains, arcs, bombs: bombs.length,
      cross: r(notes.filter(n => (n[3] === 0 && n[1] >= 2) || (n[3] === 1 && n[1] <= 1)).length / N),
      frev: r(fastRev / Math.max(1, gaps)), fast: r(fast / Math.max(1, gaps)),
      bup: r(notes.filter(n => n[2] === 0 && [0, 4, 5].includes(n[4])).length / N),
      sbsc: r(sbsc), left: r(notes.filter(n => n[3] === 0).length / N),
    };
  }
  async function one(hash, diffs) {
    const z = await openZip(`https://r2cdn.beatsaver.com/${hash.toLowerCase()}.zip`);
    const it = await z.read('info.dat');
    if (!it) throw new Error('no info');
    const out = {};
    for (const [m, d] of diffs) {
      try {
        const inf = info(it, m, d);
        if (!inf.file) { out[m + '/' + d] = 'nofile'; continue; }
        const dat = await z.read(inf.file.split('/').pop());
        out[m + '/' + d] = dat ? feat(dat, inf) : 'nodat';
      } catch (e) { out[m + '/' + d] = 'err:' + e.message; }
    }
    return out;
  }
  async function run(need, conc = 6) {
    window.BSF_RES = window.BSF_RES || {};
    const keys = Object.keys(need).filter(h => !(h in window.BSF_RES));
    let idx = 0;
    async function worker() { while (idx < keys.length) { const h = keys[idx++]; try { window.BSF_RES[h] = await one(h, need[h]); } catch (e) { window.BSF_RES[h] = 'err:' + e.message; } } }
    await Promise.all(Array.from({length: conc}, worker));
    return Object.keys(window.BSF_RES).length;
  }
  return {run, one};
})();
'ok'
