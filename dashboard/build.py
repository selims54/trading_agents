"""Build dashboard/index.html from the files in dashboard/sections, in name order.

Each section file is an HTML fragment holding one or more <section class="panel">.
The page opens by double-clicking: no server, no internet. If any section uses
Plotly, plotly.js is embedded in the page.

Placeholders any section may use:
  {{PROJECT}}         project folder name
  {{TODAY}}           today's date (YYYY-MM-DD)
  {{SETTINGS_TABLE}}  the "My settings" lines from CLAUDE.md as a table
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
SECTIONS = DASH / "sections"
OUT = DASH / "index.html"


def settings_table() -> str:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    block = re.search(r"^## My settings\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    rows = []
    for line in (block.group(1) if block else "").splitlines():
        if not line.startswith("- "):
            continue
        label, _, value = line[2:].partition(": ")
        rows.append(f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>")
    return '<table class="kv">\n' + "\n".join(rows) + "\n</table>"


def plotly_js() -> str:
    from plotly.offline import get_plotlyjs
    return f"<script>{get_plotlyjs()}</script>"


CSS = """
:root {
  --teal: #0f766e; --navy: #1e3a5f; --bronze: #a16207; --amber: #f59e0b;
  --ink: #111111; --muted: #4b5563; --paper: #f4f8fc; --grid: rgba(30,58,95,0.06);
  --panel: #ffffff; --line: rgba(15,118,110,0.55);
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  color: var(--ink);
  background-color: var(--paper);
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 24px 24px;
  font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.45;
}
header.top {
  display: flex; align-items: baseline; gap: 16px;
  padding: 20px 32px 4px; color: var(--navy);
}
header.top h1 { font-size: 20px; margin: 0; letter-spacing: 0.02em; }
header.top .hint { font-size: 12px; color: var(--muted); }
main { display: grid; gap: 24px; padding: 16px 32px 48px; max-width: 1200px; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 20px 24px 24px;
}
.panel h2 { margin: 0; font-size: 18px; color: var(--navy); }
.panel .sub { margin: 4px 0 16px; font-size: 13px; color: var(--muted); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid rgba(15,118,110,0.15); vertical-align: top; }
table.kv th { width: 210px; color: var(--teal); font-weight: 600; }
tbody tr:hover, table.kv tr:hover { background: rgba(15,118,110,0.06); }
.chart { width: 100%; height: 420px; }

/* presenter: ring and highlighter */
#ring {
  position: fixed; left: 0; top: 0; width: 38px; height: 38px; margin: -19px 0 0 -19px;
  border: 3px solid var(--amber); border-radius: 50%; pointer-events: none;
  z-index: 1000; opacity: 0; transition: opacity 0.15s;
}
#ink { position: fixed; inset: 0; pointer-events: none; z-index: 999; }
body.drawing { user-select: none; cursor: crosshair; }

/* presenter: one panel at a time */
body.present header.top, body.present main > .panel { display: none; }
body.present main > .panel.on {
  display: block; position: fixed; margin: 0; width: 960px;
  transform-origin: top left; z-index: 10;
  box-shadow: 0 4px 24px rgba(30,58,95,0.10);
}
body.present { overflow: hidden; }
"""

JS = r"""
(function () {
  // amber ring follows the mouse
  const ring = document.getElementById('ring');
  window.addEventListener('mousemove', e => {
    ring.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
    ring.style.opacity = 1;
  });
  document.addEventListener('mouseleave', () => ring.style.opacity = 0);

  // shift + drag draws an amber highlighter line that fades ~2 s after release
  const canvas = document.getElementById('ink');
  const ctx = canvas.getContext('2d');
  const strokes = [];
  let current = null;
  const HOLD = 1400, FADE = 600;
  function size() {
    const r = window.devicePixelRatio || 1;
    canvas.width = innerWidth * r; canvas.height = innerHeight * r;
    canvas.style.width = innerWidth + 'px'; canvas.style.height = innerHeight + 'px';
    ctx.setTransform(r, 0, 0, r, 0, 0);
  }
  size(); window.addEventListener('resize', size);
  window.addEventListener('mousedown', e => {
    if (!e.shiftKey || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    current = { pts: [[e.clientX, e.clientY]], released: null };
    strokes.push(current); document.body.classList.add('drawing');
  }, true);
  window.addEventListener('mousemove', e => {
    if (current) current.pts.push([e.clientX, e.clientY]);
  }, true);
  window.addEventListener('mouseup', () => {
    if (!current) return;
    current.released = performance.now(); current = null;
    document.body.classList.remove('drawing');
  }, true);
  (function draw(now) {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    for (let i = strokes.length - 1; i >= 0; i--) {
      const s = strokes[i];
      let a = 1;
      if (s.released !== null) {
        const t = now - s.released;
        if (t > HOLD + FADE) { strokes.splice(i, 1); continue; }
        if (t > HOLD) a = 1 - (t - HOLD) / FADE;
      }
      ctx.strokeStyle = `rgba(245,158,11,${0.45 * a})`;
      ctx.lineWidth = 14; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath();
      s.pts.forEach(([x, y], j) => j ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
      if (s.pts.length === 1) ctx.lineTo(s.pts[0][0] + 0.1, s.pts[0][1]);
      ctx.stroke();
    }
    requestAnimationFrame(draw);
  })(performance.now());

  // P: one panel at a time, scaled to fill the screen,
  // bottom-right 25% of width x 30% of height kept empty for the camera
  const panels = Array.from(document.querySelectorAll('main > .panel'));
  let idx = -1;
  const PAD = 24;
  function resizeCharts(el) {
    if (window.Plotly) el.querySelectorAll('.js-plotly-plot').forEach(c => Plotly.Plots.resize(c));
  }
  function place() {
    const p = panels[idx];
    panels.forEach(x => { x.classList.remove('on'); x.style.transform = ''; });
    p.classList.add('on');
    resizeCharts(p);
    const w = p.offsetWidth, h = p.offsetHeight;
    const W = innerWidth, H = innerHeight;
    // two rectangles that avoid the camera corner: full width x top 70%, or left 75% x full height
    const areas = [
      { x: 0, y: 0, w: W, h: H * 0.70 },
      { x: 0, y: 0, w: W * 0.75, h: H },
    ].map(a => ({ ...a, s: Math.min((a.w - 2 * PAD) / w, (a.h - 2 * PAD) / h) }));
    const a = areas[0].s >= areas[1].s ? areas[0] : areas[1];
    const left = a.x + (a.w - w * a.s) / 2, top = a.y + (a.h - h * a.s) / 2;
    p.style.left = left + 'px'; p.style.top = top + 'px';
    p.style.transform = `scale(${a.s})`;
  }
  function enter() {
    if (!panels.length) return;
    if (idx < 0) idx = 0;
    document.body.classList.add('present'); place();
  }
  function leave() {
    document.body.classList.remove('present');
    panels.forEach(x => { x.classList.remove('on'); x.style.transform = x.style.left = x.style.top = ''; resizeCharts(x); });
    if (idx >= 0) panels[idx].scrollIntoView({ block: 'start' });
  }
  const presenting = () => document.body.classList.contains('present');
  window.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable]')) return;
    if ((e.key === 'p' || e.key === 'P') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      presenting() ? leave() : enter(); e.preventDefault();
    } else if (presenting() && ['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(e.key)) {
      idx = Math.min(panels.length - 1, idx + 1); place(); e.preventDefault();
    } else if (presenting() && ['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) {
      idx = Math.max(0, idx - 1); place(); e.preventDefault();
    } else if (e.key === 'Escape' && presenting()) {
      leave(); e.preventDefault();
    }
  });
  window.addEventListener('resize', () => { if (presenting()) place(); });
})();
"""


def main() -> None:
    project = ROOT.name
    today = date.today().isoformat()
    files = sorted(p for p in SECTIONS.iterdir() if p.is_file() and p.suffix == ".html")
    body = []
    for f in files:
        frag = f.read_text(encoding="utf-8")
        frag = (frag.replace("{{PROJECT}}", html.escape(project))
                    .replace("{{TODAY}}", today))
        if "{{SETTINGS_TABLE}}" in frag:
            frag = frag.replace("{{SETTINGS_TABLE}}", settings_table())
        body.append(f"<!-- {f.name} -->\n{frag.strip()}")
    joined = "\n\n".join(body)
    head_js = plotly_js() if "Plotly." in joined else ""

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(project)} dashboard</title>
<style>{CSS}</style>
{head_js}
</head>
<body>
<header class="top"><h1>{html.escape(project)}</h1>
<span class="hint">P present · ←/→ step · Esc back · Shift+drag highlight</span></header>
<main>
{joined}
</main>
<canvas id="ink"></canvas>
<div id="ring"></div>
<script>{JS}</script>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"Built {OUT} from {len(files)} section(s): {', '.join(f.name for f in files)}")


if __name__ == "__main__":
    main()
