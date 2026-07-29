# Crowley setup (supported runtime)

**Supported interpreter:** Python **3.12.x** (matches CI).  
Older 3.10/3.11 may work for some paths but are **not** the recovery-foundation baseline.

Do **not** point the project at a removed or machine-specific `Python311` install path. Always create and use a project-local `venv` via the launcher or `python -m venv`.

## Create the environment

### Windows

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -U pip
.\venv\Scripts\python.exe -m pip install -r requirements-core.txt
```

Optional local ML stack (embeddings / sqlite-vec extras):

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-ml.txt
```

Or full meta install:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Always invoke Crowley through the venv interpreter:

```powershell
.\venv\Scripts\python.exe app.py
.\venv\Scripts\python.exe scripts\preflight.py
```

### macOS / Linux

```bash
python3.12 -m venv venv
./venv/bin/python -m pip install -U pip
./venv/bin/python -m pip install -r requirements-core.txt
# optional: ./venv/bin/python -m pip install -r requirements-ml.txt
./venv/bin/python app.py
```

## Configure

```bash
cp .env.example .env
# set OPENAI_API_KEY and/or local model settings
```

## Pre-change database preservation (V4.3.3R R1)

Before schema or recovery work, use the read-only inspector and existing online snapshot tooling. Neither step should mutate live rows.

Use a **unique** snapshot directory each run (do not reuse a fixed path unless you pass `--replace` under `.crowley/artifacts`):

```powershell
# Metadata + provenance only (no row-content export)
.\venv\Scripts\python.exe scripts\db_provenance.py inspect --output .crowley\artifacts\db_provenance.json

# Unique snapshot identity under managed artifacts
$stamp = Get-Date -Format "yyyyMMddTHHmmssZ"
.\venv\Scripts\python.exe scripts\db_provenance.py preserve `
  --snapshot-dir ".crowley\artifacts\prechange_$stamp" `
  --output ".crowley\artifacts\preserve_status_$stamp.json"
```

Online snapshot implementation lives in `scripts/crowley_backup.py` (reused, not replaced).  
Paths inside the repository must resolve under `.crowley/artifacts`. `--snapshot-dir`
pointing at the repo root, the live DB parent, or any path that would let
`create_snapshot`'s recursive clear delete `crowley.db` is rejected. Existing snapshot destinations are rejected by default. Public R1/preserve paths
never replace. Private backup rotation may replace only a verified Crowley bundle
that is a strict descendant of `.crowley/artifacts` or `.crowley/backup/staging` —
never the managed roots. Staging uses a collision-safe unique directory and refuses
to delete a pre-existing partial. The shared `crowley_backup.create_snapshot`
primitive finalizes and checksums `manifest.json` before promotion.

## Verify

```powershell
.\venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); import fastapi, sqlite3; print(sys.executable)"
.\venv\Scripts\python.exe -m unittest tests.test_db_provenance tests.test_crowley_backup -q
```
