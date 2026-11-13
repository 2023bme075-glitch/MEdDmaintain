# MedMaintain — Open-access medical equipment maintenance website

## Access model
- Anyone can open the public website and view/search the equipment register.
- Anyone can create a technician account; signing in is required to submit maintenance records and export CSV.
- The first administrator account is created from `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables at startup.
- Administrators can promote technicians to administrators and delete records.
- The notebook sync API is protected by `NOTEBOOK_API_KEY` when configured.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
set SECRET_KEY=replace-with-a-long-random-secret
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=use-a-long-unique-password
set NOTEBOOK_API_KEY=another-long-random-secret
python app.py
```
Open http://127.0.0.1:5000

## Deploy publicly
1. Push this folder to a private GitHub repository.
2. In Render, create a new Blueprint and connect the repository; Render reads `render.yaml`.
3. Supply `ADMIN_USERNAME` and a strong `ADMIN_PASSWORD` when prompted.
4. Deploy. Render creates a public HTTPS address and PostgreSQL database.
5. Visit the website URL and sign in with the bootstrap administrator credentials.
6. Set the same `NOTEBOOK_API_KEY` in the notebook environment (or directly in its sync cell).

The included Render plan names are examples and may incur charges; check current provider pricing before deploying. This package is source code, not a live hosted website. A hosting account and deployment approval are required to publish it.

## Notebook sync
Run `notebook_sync.py` as a cell in the attached notebook after changing `WEBSITE_API_URL` and setting the API key. It incrementally fetches entries by database ID and stores the last synchronized ID in `medmaintain_sync_state.json`. The notebook must be running to sync; website submissions remain in PostgreSQL while it is closed.

## API
- `GET /api/equipment?since_id=0` — incremental JSON list (requires `X-API-Key` if `NOTEBOOK_API_KEY` is configured)
- `GET /api/equipment/<id>` — single record JSON
- `GET /health` — health check
- `GET /export.csv` — signed-in CSV export

## Safety and privacy
The public register exposes equipment information. Do not enter patient identifiers, patient notes, passwords, or other sensitive personal data. Add organization-specific privacy, backup, access-control and retention policies before production use. The current app supports a single shared register, not separate hospital tenants.
