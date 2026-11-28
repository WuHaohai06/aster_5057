"""Record a headless-browser demo of the Aster console and encode it to MP4."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import imageio_ffmpeg
from websocket import create_connection

ROOT = Path(r"D:\courses\5057\aster_develop\Aster_5057_whh")
OUT = ROOT / "run/demo_video"
FRAMES = OUT / "frames"
CLIPS = OUT / "clips"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
URL = "http://127.0.0.1:8765/"
PORT = 9235
FPS = 10
RUN_SPEED = 4.0
RERUN_SPEED = 4.0


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = create_connection(ws_url, timeout=600)
        self.pending: dict[int, dict] = {}
        self.lock = threading.Lock()
        self.next_id = 0
        self.frames: list[tuple[float, Path]] = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _send_raw(self, method: str, params: dict | None = None) -> int:
        with self.lock:
            self.next_id += 1
            cid = self.next_id
            self.ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        return cid

    def _read(self) -> None:
        while True:
            try:
                raw = self.ws.recv()
            except Exception as error:
                if "timed out" in str(error).lower() or "timeout" in str(error).lower():
                    continue
                break
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if "id" in message:
                self.pending[message["id"]] = message
                continue
            if message.get("method") == "Page.screencastFrame":
                params = message["params"]
                data = base64.b64decode(params["data"])
                path = FRAMES / f"frame_{len(self.frames) + 1:06d}.jpg"
                path.write_bytes(data)
                self.frames.append((time.time(), path))
                self._send_raw("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    def send(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        cid = self._send_raw(method, params)
        end = time.time() + timeout
        while time.time() < end:
            message = self.pending.pop(cid, None)
            if message is not None:
                return message
            time.sleep(0.01)
        raise TimeoutError(method)

    def js(self, expression: str):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=120,
        )
        return result.get("result", {}).get("result", {}).get("value")


def wait_for(cdp: CDP, expression: str, timeout: float, label: str) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cdp.js(expression):
                print(f"ok {label} {round(timeout - (end - time.time()), 1)}s", flush=True)
                return True
        except Exception:
            pass
        time.sleep(1)
    print(f"TIMEOUT {label}", flush=True)
    return False


def click_text(cdp: CDP, text: str, contains: bool = False) -> bool:
    needle = json.dumps(text)
    if contains:
        match = f"(e.textContent||'').includes({needle})"
    else:
        match = f"(e.textContent||'').trim() === {needle}"
    expr = (
        "(() => { const el = Array.from(document.querySelectorAll('button')).find(e => "
        + match
        + " && !e.disabled); if (el) { el.click(); return true; } return false; })()"
    )
    return bool(cdp.js(expr))


def build_video(frames: list[tuple[float, Path]], markers: list[tuple[str, float]]) -> Path:
    if not frames:
        raise RuntimeError("no frames captured")
    rerun_start = next((t for label, t in markers if label == "rerun_start"), None)
    rerun_end = next((t for label, t in markers if label == "rerun_end"), None)
    run_start = next((t for label, t in markers if label == "run_start"), None)
    run_end = next((t for label, t in markers if label == "run_end"), None)
    windows = []
    prep_start = next((t for label, t in markers if label == "prepare_start"), None)
    prep_end = next((t for label, t in markers if label == "prepare_end"), None)
    if prep_start and prep_end:
        windows.append((prep_start, prep_end, 6.0))
    if rerun_start and rerun_end:
        windows.append((rerun_start, rerun_end, RERUN_SPEED))
    if run_start and run_end:
        windows.append((run_start, run_end, RUN_SPEED))

    t0 = frames[0][0]
    total = 0.0
    cursor = t0
    for start, end, speed in sorted(windows):
        if start > cursor:
            total += (start - cursor)
        total += max(0.0, (end - start)) / speed
        cursor = max(cursor, end)
    total += max(0.0, frames[-1][0] - cursor)

    CLIPS.mkdir(parents=True, exist_ok=True)
    for old in CLIPS.glob("out_*.jpg"):
        old.unlink()

    steps = max(1, int(total * FPS))
    index = 0
    for step in range(steps):
        out_t = step / FPS
        # map output time to source time
        src_t = t0
        remaining = out_t
        cursor = t0
        for start, end, speed in sorted(windows):
            span = max(0.0, start - cursor)
            if remaining <= span:
                src_t = cursor + remaining
                break
            remaining -= span
            cursor = max(cursor, start)
            span = max(0.0, end - cursor)
            if remaining <= span / speed:
                src_t = cursor + remaining * speed
                break
            remaining -= span / speed
            cursor = max(cursor, end)
        else:
            src_t = cursor + remaining
        while index + 1 < len(frames) and frames[index + 1][0] <= src_t:
            index += 1
        shutil.copyfile(frames[index][1], CLIPS / f"out_{step + 1:05d}.jpg")

    video = OUT / "aster_ui_demo.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg, "-y", "-framerate", str(FPS), "-i", str(CLIPS / "out_%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-movflags", "+faststart", str(video),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return video


def main() -> int:
    for directory in (FRAMES, CLIPS):
        directory.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob("frame_*.jpg"):
        old.unlink()

    profile = OUT / "edge_profile"
    profile.mkdir(exist_ok=True)
    process = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    markers: list[tuple[str, float]] = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        request = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/json/new?{URL}", method="PUT"
        )
        target = json.load(urllib.request.urlopen(request, timeout=5))
        cdp = CDP(target["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": 1600, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        cdp.send("Page.navigate", {"url": URL})
        time.sleep(5)
        cdp.send("Page.startScreencast",
                 {"format": "jpeg", "quality": 78, "maxWidth": 1600, "maxHeight": 900, "everyNthFrame": 1})
        markers.append(("start", time.time()))

        def scroll(top: int, wait: float = 2.2) -> None:
            cdp.js(f"window.scrollTo({{top: {top}, behavior: 'smooth'}})")
            time.sleep(wait)

        # Command Center
        time.sleep(3)
        scroll(640)
        scroll(0, 1.2)

        click_text(cdp, "Factor Library")
        time.sleep(2.5)
        scroll(500, 2.0)
        cdp.js("document.querySelector('tbody tr')?.click()")
        time.sleep(2.5)
        cdp.js("document.querySelector('.drawer-close')?.click()")
        scroll(0, 1.0)

        click_text(cdp, "AI Council")
        time.sleep(2.5)
        scroll(800)
        scroll(1700)
        scroll(0, 1.2)

        click_text(cdp, "Filing Intelligence")
        time.sleep(2.5)
        scroll(650)
        scroll(0, 1.2)

        click_text(cdp, "Portfolio Replay")
        time.sleep(2)
        click_text(cdp, "Start interactive quarterly replay", contains=True)
        wait_for(cdp, "(() => { const t = document.querySelector('.replay-human textarea'); return !!t && !t.disabled; })()", 120, "prepared")
        scroll(430, 1.5)
        prompt = (
            "Reconsider factor redundancy: keep only one short-horizon reversal sleeve, keep "
            "conventional_low_vol as the defensive anchor, disable momentum groups whose 2026 "
            "Rank IC is unstable, and keep the approved portfolio profile and industries unchanged."
        )
        cdp.js(
            "(() => { const t = document.querySelector('.replay-human textarea'); if (!t) return false; "
            "const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set; "
            f"setter.call(t, {json.dumps(prompt)}); t.dispatchEvent(new Event('input', {{bubbles:true}})); return true; }})()"
        )
        time.sleep(1)
        markers.append(("rerun_start", time.time()))
        click_text(cdp, "Rerun both agendas", contains=True)
        wait_for(cdp, "document.querySelectorAll('.replay-rounds article').length >= 2", 240, "round1")
        markers.append(("rerun_end", time.time()))
        time.sleep(1)
        scroll(700, 2.0)
        wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').trim() === 'Accept decision package' && !e.disabled)", 30, "accept enabled")
        click_text(cdp, "Accept decision package")
        wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').includes('Package accepted'))", 30, "accepted")
        time.sleep(1)
        markers.append(("run_start", time.time()))
        click_text(cdp, "Run segment")
        wait_for(cdp, "Array.from(document.querySelectorAll('button')).some(e => (e.textContent||'').trim() === 'Play' && !e.disabled)", 360, "ready")
        markers.append(("run_end", time.time()))
        time.sleep(1)
        scroll(900, 1.5)
        click_text(cdp, "Play")
        time.sleep(6)
        scroll(1600, 2.0)
        time.sleep(1.5)
        cdp.send("Page.stopScreencast")
        time.sleep(1)
        video = build_video(cdp.frames, markers)
        print(f"video: {video}", flush=True)
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
