# MedMaintain — Medical equipment maintenance register

## Access model
- Anyone can open the public website and view/search the equipment register.
- Anyone can create a technician account; signing in is required to submit maintenance records and export CSV.
- The first administrator account is created from the `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables at startup.
- Administrators can promote technicians to administrators and delete records.
- The notebook sync API is protected by `NOTEBOOK_API_KEY` when configured.

## Project structure
- `app.py` — Flask application, authentication, equipment records and API.
- `templates/` — HTML templates rendered by Flask.
- `static/style.css` — responsive website styling.
- `notebook_sync.py` — incremental synchronization helper for the Jupyter notebook.

Keep the HTML files inside `templates/` and CSS, JavaScript or images inside `static/`; Flask expects these folders by default.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set the following environment variables before starting the app:
- `SECRET_KEY` — long random value used to protect sessions.
- `ADMIN_USERNAME` — initial administrator username.
- `ADMIN_PASSWORD` — strong initial administrator password (at least 10 characters).
- `NOTEBOOK_API_KEY` — long random key used by notebook synchronization.

Then run:
```bash
python app.py
```
Open http://127.0.0.1:5000

## Public deployment
The repository includes a `Procfile` for hosts that support Python web services and a `render.yaml` Blueprint configuration. **Check the hosting provider's current prices and database limits before deploying:** the current Render Blueprint specifies paid service/database plans and is not a guaranteed free deployment. A GitHub repository alone does not make the Flask website publicly accessible.

When deploying, configure `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` and `NOTEBOOK_API_KEY` as private environment variables in the hosting dashboard. Never commit real passwords or API keys to GitHub.

## Notebook sync
Run `notebook_sync.py` from a cell in the Jupyter notebook after setting `WEBSITE_API_URL` to the deployed website's base URL and configuring the same `NOTEBOOK_API_KEY`. The helper fetches new records incrementally by database ID and stores its last synchronized ID in `medmaintain_sync_state.json`. The notebook must be running when synchronization is performed; submissions remain on the website while the notebook is closed.

## API
- `GET /api/equipment?since_id=0` — incremental JSON list (requires `X-API-Key` if `NOTEBOOK_API_KEY` is configured).
- `GET /api/equipment/<id>` — single record JSON.
- `GET /health` — health check.
- `GET /export.csv` — signed-in CSV export.

## Safety and privacy
The public register exposes equipment information. Do not enter patient identifiers, patient notes, passwords, or other sensitive personal data. Establish organization-specific privacy, backup, access-control and retention policies before production use. The current app supports one shared register, not separate hospital tenants.
