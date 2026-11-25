# Aster Research Console

Interactive, read-only research dashboard for the Aster project.

## Live mode

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_aster_console_live.ps1
```

Open `http://127.0.0.1:8765/`. FastAPI serves the production bundle and a
sanitised `/api/snapshot`; the browser refreshes through SSE and a 15-second
polling fallback. The API has no mutation endpoints.

The live service and static exporter do not include API keys, raw LLM
responses, PDFs, large Parquet files, process IDs, log paths or absolute source
paths.

## Frontend development

```powershell
./scripts/start_aster_console_live.ps1 -NoBuild
cd .\apps\aster-console
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`.

## Static fallback

```powershell
python .\scripts\export_dashboard_snapshot.py
```

If the live API is unavailable, the browser falls back to
`public/data/snapshot.json` and marks the connection as `SNAPSHOT`.

## Build

```powershell
npm run build
```

The static production bundle is written to `dist/`.
