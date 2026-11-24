# Aster Research Console

Interactive, read-only research dashboard for the Aster project.

## Refresh the workspace snapshot

From the repository root:

```powershell
python .\scripts\export_dashboard_snapshot.py
```

The exporter writes only sanitised, downsampled data. It does not include API
keys, raw LLM responses, PDFs, large Parquet files or absolute source paths.

## Run locally

```powershell
cd .\apps\aster-console
npm install
npm run dev
```

## Build

```powershell
npm run build
```

The static production bundle is written to `dist/`.
