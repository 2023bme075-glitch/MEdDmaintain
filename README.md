# MedMaintain — Medical equipment maintenance register

## Access model
- Anyone can open the public website and view/search the equipment register.
- Technician registration is restricted to `ALLOWED_EMAIL_DOMAINS`; new accounts require supervisor approval. The initial owner is created once through `/owner-setup` using a private one-time `OWNER_SETUP_TOKEN` and the exact `OWNER_EMAIL`. Supervisors review new maintenance records before they appear in the approved register. Only the owner can assign supervisor privileges.
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
- `ALLOWED_EMAIL_DOMAINS` — comma-separated approved email domains for technician registration.
- `OWNER_EMAIL` — exact email address reserved for the initial owner setup.
- `OWNER_SETUP_TOKEN` — one-time random secret of at least 32 characters, configured privately and removed after owner setup.
- `NOTEBOOK_API_KEY` — long random key used by notebook synchronization.

Then run:
```bash
python app.py
```
Open http://127.0.0.1:5000

## Public deployment
The repository includes a `Procfile` for hosts that support Python web services and a `render.yaml` Blueprint configuration. **Check the hosting provider's current prices and database limits before deploying:** the current Render Blueprint specifies paid service/database plans and is not a guaranteed free deployment. A GitHub repository alone does not make the Flask website publicly accessible.

When deploying, configure `SECRET_KEY`, `ALLOWED_EMAIL_DOMAINS`, `OWNER_EMAIL`, `OWNER_SETUP_TOKEN` and `NOTEBOOK_API_KEY` as private environment variables in the hosting dashboard. Never commit real passwords or API keys to GitHub.


## Deploy on PythonAnywhere's free plan (no card)
The application uses SQLite by default, so a PostgreSQL service is not required for this option.

1. Create a free Beginner account at https://www.pythonanywhere.com/ and verify your email. The free account supports one web app at `yourusername.pythonanywhere.com`.
2. Open **Consoles → Bash** and clone this public repository:
   ```bash
   git clone https://github.com/2023bme075-glitch/MEdDmaintain.git
   cd MEdDmaintain
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   If Git cloning is blocked on the free account, download the repository ZIP from GitHub and upload/extract it using the Files page instead.
3. Open **Web → Add a new web app**. Choose the free `yourusername.pythonanywhere.com` address, then choose **Manual configuration** and a Python version supported by the account.
4. In the Web tab, set the **Source code** directory to `/home/yourusername/MEdDmaintain` and the **Working directory** to the same path. Replace `yourusername` with your PythonAnywhere username.
5. Open the WSGI configuration file linked on the Web tab. Replace its contents with the following, changing the username and the two secret values:
   ```python
   import os
   import sys

   project_home = "/home/yourusername/MEdDmaintain"
   if project_home not in sys.path:
       sys.path.insert(0, project_home)

   os.environ["SECRET_KEY"] = "REPLACE_WITH_A_LONG_RANDOM_SECRET"
   os.environ["ADMIN_USERNAME"] = "REPLACE_WITH_YOUR_ADMIN_USERNAME"
   os.environ["ADMIN_PASSWORD"] = "REPLACE_WITH_A_LONG_UNIQUE_PASSWORD"
   os.environ["NOTEBOOK_API_KEY"] = "REPLACE_WITH_ANOTHER_LONG_RANDOM_SECRET"

   from app import app as application
   ```
   Keep these real secrets in the private WSGI configuration only. Do not commit them to GitHub or share them in chat.
6. In the Web tab's **Virtualenv** field, enter `/home/yourusername/MEdDmaintain/.venv`.
7. Under **Static files**, add URL `/static/` mapped to `/home/yourusername/MEdDmaintain/static/`.
8. Click **Reload**, then open `https://yourusername.pythonanywhere.com/health`. A working app returns JSON containing `"ok": true`; then open the home page and sign in using the administrator credentials you set above.
9. In the Jupyter notebook, set `WEBSITE_API_URL` to your new HTTPS website address and use the same `NOTEBOOK_API_KEY` value. Run the notebook sync cell when you want to import new records.

**Free-plan limitations:** PythonAnywhere currently lists one web app, 512 MiB of disk, and a one-month web-app expiry/renewal requirement for free accounts. New free accounts also have restricted outbound internet and do not include MySQL or scheduled tasks. The app's SQLite database is stored on the persistent account filesystem; download backups regularly. Visit the provider's current plan page before relying on the service for operational or clinical use.

## Notebook sync
Run `notebook_sync.py` from a cell in the Jupyter notebook after setting `WEBSITE_API_URL` to the deployed website's base URL and configuring the same `NOTEBOOK_API_KEY`. The helper fetches new records incrementally by database ID and stores its last synchronized ID in `medmaintain_sync_state.json`. The notebook must be running when synchronization is performed; submissions remain on the website while the notebook is closed.

## API
- `GET /api/equipment?since_id=0` — incremental JSON list (requires `X-API-Key` if `NOTEBOOK_API_KEY` is configured).
- `GET /api/equipment/<id>` — single record JSON.
- `GET /health` — health check.
- `GET /export.csv` — signed-in CSV export.

## Safety and privacy
The public register exposes equipment information. Do not enter patient identifiers, patient notes, passwords, or other sensitive personal data. Establish organization-specific privacy, backup, access-control and retention policies before production use. The current app supports one shared register, not separate hospital tenants.


## Account security and supervisor workflow
1. In the PythonAnywhere WSGI configuration, set `ALLOWED_EMAIL_DOMAINS` to the comma-separated domains approved by your institution(s), for example `hospital.org,university.ac.ug`. Use the exact domains your organization authorizes. If this variable is missing, new technician registration is disabled.
2. Set `OWNER_EMAIL` to the exact email address that will belong to the site owner. Set `OWNER_SETUP_TOKEN` to a newly generated random secret of at least 32 characters. Keep both values private; never put them in GitHub or chat.
3. Reload the app, then open the private setup address `/owner-setup`. Enter the token, designated email, a username (default suggestion: `medmaintain_owner`) and a unique password of at least 14 characters. The first owner account is created only once.
4. Immediately remove `OWNER_SETUP_TOKEN` from the WSGI configuration and reload the app. The setup page is also permanently disabled after an owner account exists.
5. Technicians register with an approved organization email and wait for approval. The owner can appoint supervisors from **Owner controls**. Supervisors approve technician accounts and approve or return maintenance entries from the **Supervisor portal**.
6. Notebook POST submissions are also queued for supervisor review. The notebook GET endpoint returns approved records only.

The domain allowlist checks the email address's domain; it does not independently prove control of that mailbox. The private one-time owner token is the proof of control for initial owner creation. If mailbox ownership verification is required for technicians, add an organization email-verification service before enabling registration. The additive database migration preserves existing accounts and treats legacy accounts/records as approved; review those existing accounts after upgrading.
