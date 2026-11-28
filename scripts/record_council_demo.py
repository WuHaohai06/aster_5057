"""Record a focused interactive-council demo at the 2026-06-30 node."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import record_ui_demo as rec
rec.RUN_SPEED = 20.0
rec.RERUN_SPEED = 8.0

ROOT = Path(r"D:\courses\5057\aster_develop\Aster_5057_whh")
OUT = ROOT / "run/demo_video_council"
rec.OUT = OUT
rec.FRAMES = OUT / "frames"
rec.CLIPS = OUT / "clips"
EDGE = rec.EDGE
PORT = 9236
URL = "http://127.0.0.1:8765/?start_node=2026-06-30"

PROMPT = (
    "Reconsider factor redundancy: keep only one short-horizon reversal sleeve, keep "
    "conventional_low_vol as the defensive anchor, disable momentum groups whose 2026 "
    "Rank IC is unstable, and keep the approved portfolio profile and industries unchanged."
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frames").mkdir(exist_ok=True)
    (OUT / "clips").mkdir(exist_ok=True)
    for old in (OUT / "frames").glob("frame_*.jpg"):
        old.unlink()

    profile = OUT / "edge_profile"
    profile.mkdir(exist_ok=True)
    process = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    markers = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        request = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{URL}", method="PUT")
        target = json.load(urllib.request.urlopen(request, timeout=5))
        cdp = rec.CDP(target["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": 1600, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        cdp.send("Page.navigate", {"url": URL})
        time.sleep(5)
        cdp.send("Page.startScreencast",
                 {"format": "jpeg", "quality": 78, "maxWidth": 1600, "maxHeight": 900, "everyNthFrame": 1})
        markers.append(("start", time.time()))

        rec.click_text(cdp, "Portfolio Replay")
        time.sleep(2.5)
        rec.click_text(cdp, "Start interactive quarterly replay", contains=True)
        rec.wait_for(cdp, "(() => { const t = document.querySelector('.replay-human textarea'); return !!t && !t.disabled; })()", 90, "prepared")
        cdp.js("""(() => {
          const banner = document.createElement('div');
          banner.textContent = '2026-06-30 · tech-crash scenario · interactive council';
          Object.assign(banner.style, {position:'fixed', top:'12px', left:'50%', transform:'translateX(-50%)',
            zIndex:'9999', background:'#06232b', color:'#31d7c7', padding:'6px 14px',
            border:'1px solid #31d7c7', borderRadius:'4px', font:'600 13px monospace'});
          document.body.appendChild(banner);
          document.querySelectorAll('.replay-timeline').forEach((tl) => { tl.scrollLeft = tl.scrollWidth; });
          const active = document.querySelector('.replay-timeline button.active');
          if (active) active.scrollIntoView({inline: 'center', block: 'nearest'});
          return true;
        })()""")
        time.sleep(2)
        time.sleep(1)
        cdp.js("document.querySelector('.replay-human')?.scrollIntoView({block: 'center'})")
        time.sleep(1.5)
        cdp.js(
            "(() => { const t = document.querySelector('.replay-human textarea'); if (!t) return false; "
            "const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set; "
            f"setter.call(t, {json.dumps(PROMPT)}); t.dispatchEvent(new Event('input', {{bubbles:true}})); return true; }})()"
        )
        time.sleep(1.5)
        markers.append(("rerun_start", time.time()))
        rec.click_text(cdp, "Rerun both agendas", contains=True)
        rec.wait_for(cdp, "document.querySelectorAll('.replay-rounds article').length >= 2", 300, "round1")
        markers.append(("rerun_end", time.time()))
        time.sleep(1)
        cdp.js("document.querySelector('.replay-portfolio-agenda')?.scrollIntoView({block: 'start'})")
        time.sleep(2)
        rec.wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').trim() === 'Accept decision package' && !e.disabled)", 60, "accept enabled")
        rec.click_text(cdp, "Accept decision package")
        rec.wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').includes('Package accepted'))", 60, "accepted")
        time.sleep(1)
        markers.append(("run_start", time.time()))
        rec.click_text(cdp, "Run segment")
        rec.wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').trim() === 'Play' && !e.disabled)", 900, "ready")
        markers.append(("run_end", time.time()))
        time.sleep(1)
        cdp.js("document.querySelector('.replay-player')?.scrollIntoView({block: 'center'})")
        time.sleep(1.5)
        rec.click_text(cdp, "Play")
        time.sleep(10)
        cdp.send("Page.stopScreencast")
        time.sleep(1)
        video = rec.build_video(cdp.frames, markers)
        final = OUT / "aster_council_demo.mp4"
        shutil.move(str(video), str(final))
        print(f"video: {final}", flush=True)
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
