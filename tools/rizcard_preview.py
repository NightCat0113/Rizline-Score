"""Temporary local rizcard playground — pair layout / bio / art without Discord.

  python tools/rizcard_preview.py
  python tools/rizcard_preview.py --port 8765

Open http://127.0.0.1:8765/ — pick options, hit Render (or leave auto on).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import FONT_FILENAME, REPO_ROOT  # noqa: E402
from bot.services.collection import collection_rows  # noqa: E402
from bot.services.songdata import SongIndex  # noqa: E402
from bot.ui.b40_image import render_rizcard  # noqa: E402

ILLUST_HIRES = REPO_ROOT / "output" / "illust_HiRes"
ILLUST = REPO_ROOT / "output" / "illust"
FONT = REPO_ROOT / "assets" / "fonts" / FONT_FILENAME
SONGS = REPO_ROOT / "bot" / "static" / "songs_index.json"


def _options() -> dict:
    songs = SongIndex.load(SONGS) if SONGS.is_file() else None
    layouts = collection_rows(REPO_ROOT, "en", "layout")
    bios = collection_rows(REPO_ROOT, "en", "bio")
    arts = collection_rows(REPO_ROOT, "en", "illustration", songs)
    return {
        "layouts": layouts,
        "bios": bios,
        "arts": arts,
        "defaults": {
            "username": "NightXWind",
            "layoutId": "layout.00037",
            "bioStem": next((row["id"] for row in bios if "Musical" in row.get("name", "")), bios[0]["id"] if bios else ""),
            "bioMode": "both",
            "backgroundId": next(
                (row["id"] for row in arts if "slichertz" in row["id"].casefold() or "slic" in row.get("name", "").casefold()),
                arts[0]["id"] if arts else "",
            ),
            "avatarId": "",
            "language": "en",
        },
    }


def _bio_ids(stem: str, mode: str) -> tuple[str, str]:
    cleaned = stem.strip()
    if not cleaned:
        return "", ""
    if cleaned.startswith("bio.") and (cleaned.endswith(".1") or cleaned.endswith(".2")):
        return (cleaned, "") if cleaned.endswith(".1") else ("", cleaned)
    one = f"bio.{cleaned}.1"
    two = f"bio.{cleaned}.2"
    if mode == "1":
        return one, ""
    if mode == "2":
        return "", two
    return one, two


def _render(query: dict[str, list[str]]) -> bytes:
    def one(key: str, default: str = "") -> str:
        values = query.get(key) or []
        return values[0] if values else default

    bio1, bio2 = _bio_ids(one("bioStem"), one("bioMode", "both"))
    # Allow explicit overrides.
    if one("bioId1") or one("bioId2"):
        bio1, bio2 = one("bioId1"), one("bioId2")
    avatar = one("avatarId").strip()
    background = one("backgroundId").strip()
    if not avatar:
        avatar = background
    card = {
        "layoutId": one("layoutId", "layout.00037"),
        "backgroundId": background,
        "avatarId": avatar,
        "bioId1": bio1,
        "bioId2": bio2,
        "avatarPos": {"x": 0.5, "y": 0.5, "z": 1.0},
    }
    return render_rizcard(
        username=one("username", "Player") or "Player",
        total_rks=0.0,
        illust_hires_dir=ILLUST_HIRES,
        illust_dir=ILLUST,
        font_path=FONT,
        repo_root=REPO_ROOT,
        card=card,
        language=one("language", "en") or "en",
    )


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Rizcard Preview (temp)</title>
<style>
  :root {
    --bg: #1a1b1e;
    --panel: #25262b;
    --text: #e8e8ea;
    --muted: #9a9aa0;
    --accent: #6ea8fe;
    --border: #3a3b40;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font: 14px/1.4 system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh;
  }
  header {
    padding: 14px 20px; border-bottom: 1px solid var(--border);
    display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 650; }
  header span { color: var(--muted); font-size: 12px; }
  main {
    display: grid;
    grid-template-columns: minmax(280px, 360px) 1fr;
    gap: 0; min-height: calc(100vh - 52px);
  }
  @media (max-width: 860px) {
    main { grid-template-columns: 1fr; }
  }
  aside {
    padding: 16px; border-right: 1px solid var(--border);
    background: var(--panel); overflow: auto;
  }
  label { display: block; margin: 0 0 4px; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
  .field { margin-bottom: 12px; }
  input[type=text], select {
    width: 100%; padding: 8px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: #15161a; color: var(--text);
  }
  select { max-width: 100%; }
  .row { display: flex; gap: 8px; }
  .row > * { flex: 1; }
  button {
    width: 100%; padding: 10px 12px; border: 0; border-radius: 8px;
    background: var(--accent); color: #0b1220; font-weight: 650; cursor: pointer;
  }
  button:disabled { opacity: .5; cursor: wait; }
  .check { display: flex; align-items: center; gap: 8px; color: var(--text); text-transform: none; letter-spacing: 0; font-size: 13px; margin-top: 8px; }
  .check input { accent-color: var(--accent); }
  .hint { color: var(--muted); font-size: 12px; margin-top: 8px; }
  .status { min-height: 1.2em; margin-top: 8px; color: var(--muted); font-size: 12px; }
  .status.err { color: #ff8e8e; white-space: pre-wrap; }
  section.preview {
    padding: 16px; display: flex; align-items: flex-start; justify-content: center;
    overflow: auto; background: #121318;
  }
  #card {
    max-width: min(100%, 520px); width: 100%; height: auto;
    border-radius: 12px; background: #0002; box-shadow: 0 12px 40px #0008;
  }
  #card[hidden] { display: none; }
</style>
</head>
<body>
<header>
  <h1>Rizcard preview</h1>
  <span>temporary local tool — no Discord</span>
</header>
<main>
  <aside>
    <div class="field">
      <label>Username</label>
      <input id="username" type="text" autocomplete="off"/>
    </div>
    <div class="field">
      <label>Layout</label>
      <select id="layoutId"></select>
    </div>
    <div class="field">
      <label>Bio</label>
      <select id="bioStem"></select>
      <div class="row" style="margin-top:8px">
        <div>
          <label>Parts</label>
          <select id="bioMode">
            <option value="both">title1 + title2</option>
            <option value="1">title1 only</option>
            <option value="2">title2 only</option>
          </select>
        </div>
      </div>
      <div class="hint" id="bioPreview"></div>
    </div>
    <div class="field">
      <label>Art (background)</label>
      <input id="artFilter" type="text" placeholder="filter arts…" autocomplete="off"/>
      <select id="backgroundId" size="12" style="margin-top:6px; height: 220px;"></select>
    </div>
    <div class="field">
      <label>Avatar (empty = same as art)</label>
      <select id="avatarId"></select>
    </div>
    <button id="renderBtn" type="button">Render</button>
    <label class="check"><input id="auto" type="checkbox" checked/> Auto-render on change</label>
    <div class="status" id="status"></div>
  </aside>
  <section class="preview">
    <img id="card" alt="rizcard preview" hidden/>
  </section>
</main>
<script>
const els = {
  username: document.getElementById('username'),
  layoutId: document.getElementById('layoutId'),
  bioStem: document.getElementById('bioStem'),
  bioMode: document.getElementById('bioMode'),
  bioPreview: document.getElementById('bioPreview'),
  artFilter: document.getElementById('artFilter'),
  backgroundId: document.getElementById('backgroundId'),
  avatarId: document.getElementById('avatarId'),
  renderBtn: document.getElementById('renderBtn'),
  auto: document.getElementById('auto'),
  status: document.getElementById('status'),
  card: document.getElementById('card'),
};
let arts = [];
let bios = [];
let timer = null;

function fillSelect(sel, rows, valueKey='id', labelFn=r=>r.name || r.id, includeBlank=false) {
  sel.innerHTML = '';
  if (includeBlank) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = '(same as art)';
    sel.appendChild(o);
  }
  for (const row of rows) {
    const o = document.createElement('option');
    o.value = row[valueKey];
    o.textContent = labelFn(row);
    sel.appendChild(o);
  }
}

function updateBioPreview() {
  const row = bios.find(b => b.id === els.bioStem.value);
  if (!row) { els.bioPreview.textContent = ''; return; }
  const mode = els.bioMode.value;
  const text = mode === '1' ? row.title1 : mode === '2' ? row.title2 : row.name;
  els.bioPreview.textContent = text || '';
}

function filterArts() {
  const q = els.artFilter.value.trim().toLowerCase();
  const filtered = !q ? arts : arts.filter(a =>
    (a.id || '').toLowerCase().includes(q) || (a.name || '').toLowerCase().includes(q)
  );
  const current = els.backgroundId.value;
  fillSelect(els.backgroundId, filtered, 'id', a => `${a.name}  ·  ${a.id}`);
  if ([...els.backgroundId.options].some(o => o.value === current)) {
    els.backgroundId.value = current;
  }
}

function queryString() {
  const p = new URLSearchParams({
    username: els.username.value,
    layoutId: els.layoutId.value,
    bioStem: els.bioStem.value,
    bioMode: els.bioMode.value,
    backgroundId: els.backgroundId.value,
    avatarId: els.avatarId.value,
  });
  return p.toString();
}

async function renderNow() {
  els.renderBtn.disabled = true;
  els.status.className = 'status';
  els.status.textContent = 'Rendering…';
  const url = '/render?' + queryString() + '&_=' + Date.now();
  try {
    const res = await fetch(url);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || res.statusText);
    }
    const blob = await res.blob();
    const obj = URL.createObjectURL(blob);
    const prev = els.card.dataset.url;
    els.card.src = obj;
    els.card.hidden = false;
    els.card.dataset.url = obj;
    if (prev) URL.revokeObjectURL(prev);
    els.status.textContent = `OK · ${(blob.size/1024).toFixed(0)} KB`;
  } catch (err) {
    els.status.className = 'status err';
    els.status.textContent = String(err.message || err);
  } finally {
    els.renderBtn.disabled = false;
  }
}

function schedule() {
  if (!els.auto.checked) return;
  clearTimeout(timer);
  timer = setTimeout(renderNow, 280);
}

async function boot() {
  const res = await fetch('/options');
  const data = await res.json();
  arts = data.arts || [];
  bios = data.bios || [];
  fillSelect(els.layoutId, data.layouts || []);
  fillSelect(els.bioStem, bios, 'id', b => `${b.name}  (${b.id})`);
  fillSelect(els.avatarId, arts, 'id', a => `${a.name}  ·  ${a.id}`, true);
  filterArts();
  const d = data.defaults || {};
  els.username.value = d.username || 'Player';
  if (d.layoutId) els.layoutId.value = d.layoutId;
  if (d.bioStem) els.bioStem.value = d.bioStem;
  if (d.bioMode) els.bioMode.value = d.bioMode;
  if (d.backgroundId) {
    els.backgroundId.value = d.backgroundId;
    if (els.backgroundId.value !== d.backgroundId) {
      // ensure selected even if filter somehow missed
      const opt = document.createElement('option');
      opt.value = d.backgroundId; opt.textContent = d.backgroundId;
      els.backgroundId.prepend(opt);
      els.backgroundId.value = d.backgroundId;
    }
  }
  if (d.avatarId) els.avatarId.value = d.avatarId;
  updateBioPreview();
  els.renderBtn.addEventListener('click', renderNow);
  for (const el of [els.username, els.layoutId, els.bioStem, els.bioMode, els.backgroundId, els.avatarId]) {
    el.addEventListener('change', () => { updateBioPreview(); schedule(); });
  }
  els.username.addEventListener('input', schedule);
  els.artFilter.addEventListener('input', () => { filterArts(); });
  await renderNow();
}
boot();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/options":
                payload = json.dumps(_options(), ensure_ascii=False).encode("utf-8")
                self._send(200, payload, "application/json; charset=utf-8")
                return
            if path == "/render":
                query = urllib.parse.parse_qs(parsed.query)
                png = _render(query)
                self._send(200, png, "image/png")
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")
        except Exception:
            detail = traceback.format_exc()
            self._send(500, detail.encode("utf-8"), "text/plain; charset=utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Temporary local rizcard preview")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not FONT.is_file():
        print(f"font missing: {FONT}", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Rizcard preview at {url}")
    print("Ctrl+C to stop")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
