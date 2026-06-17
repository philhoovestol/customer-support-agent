# Deploying To Render Starter

This guide deploys the React frontend and FastAPI backend as one Render web
service. A 1 GB persistent disk stores the SQLite database, so refund cases and
audit events survive deploys and restarts.

## What Render Will Create

- One Docker-based web service on the `Starter` instance type in Oregon.
- One 1 GB persistent disk mounted at `/var/data`.
- One public `https://<service-name>.onrender.com` URL.
- Automatic deploys whenever a commit reaches the repository's default branch.
- A health check against `/api/health`.

The configuration lives in `render.yaml`. As of June 17, 2026, the expected
base cost is about $7.25 per month: $7 for the Starter service and $0.25 for a
1 GB disk. Render displays the current price before creating the resources;
review that amount because pricing can change.

## Before You Start

You need:

1. A GitHub account.
2. A Render account with a payment method.
3. Git installed locally.

The project is already hosted in a GitHub repository. The deployment steps
below begin with connecting that repository to Render.

The default deployment uses the deterministic mock LLM. It does not require an
OpenAI key and does not create OpenAI usage charges.

Never commit `backend/.env`, `backend/support_agent.db`, or an API key. They are
already excluded by `.gitignore` and `.dockerignore`.

## 1. Verify The Project Locally

Run the backend tests:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..
```

Build the frontend:

```powershell
cd frontend
npm ci
npm run build
cd ..
```

## 2. Create The Render Blueprint

1. Sign in at [dashboard.render.com](https://dashboard.render.com/).
2. Open **New**, then choose **Blueprint**.
3. Connect GitHub if prompted and grant Render access to the repository.
4. Select the repository containing this project.
5. Keep the Blueprint path as `render.yaml`.
6. Review the detected `loopp-customer-support-agent` web service.
7. Confirm that the instance type is **Starter** and that a 1 GB persistent
   disk is attached at `/var/data`.
8. Review the displayed monthly cost, then deploy the Blueprint.

Render builds the React app in a Node build stage, installs the Python backend,
and starts Uvicorn on Render's assigned `PORT`. The first build can take several
minutes. Follow it from the service's **Events** or **Logs** page.

## 3. Open And Verify The Deployment

When the deploy is live, open the service's `onrender.com` URL. The full app
should load at the root URL.

Check the health endpoint in a browser:

```text
https://YOUR-SERVICE.onrender.com/api/health
```

The response should resemble:

```json
{"status":"ok","app":"Loopp Refund Support Agent"}
```

In the UI, submit a sample request:

```text
I need a refund for ORD-1002. The headphones are uncomfortable.
```

Confirm that the response, refund case, and audit events appear. Trigger a
manual deploy from Render and confirm the new case remains afterward; this
verifies that SQLite is using the persistent disk.

## 4. Optional: Use OpenAI Instead Of The Mock LLM

The mock provider is best for a predictable, zero-API-cost submission demo. To
use OpenAI instead:

1. Open the web service in Render.
2. Open **Environment**.
3. Change `LLM_PROVIDER` from `mock` to `openai`.
4. Add `OPENAI_API_KEY` as a secret environment variable.
5. Optionally add `OPENAI_MODEL`; the app defaults to `gpt-4.1-mini`.
6. Save the changes and allow Render to redeploy.

Do not add the key to `render.yaml` or any committed file. OpenAI API usage is
billed separately from Render.

## 5. Deploy Updates

The Blueprint enables deploys on every commit. Push changes normally:

```powershell
git add .
git commit -m "Describe the change"
git push
```

Render will build and deploy the new commit. Database contents remain on the
attached disk.

## 6. Reset The Demo Database

The reset removes generated cases and audit events and restores the seed data.
Run it only while nobody is using the demo:

1. Open the service's **Shell** page in Render.
2. Run:

```bash
cd /app/backend
python scripts/reset_db.py
```

The command uses `DATABASE_URL`, so it resets the database on `/var/data`, not
the disposable filesystem inside the Docker image.

## 7. Troubleshooting

### The root URL returns an API-only response or 404

Check the build log for a successful `npm run build`. The Docker image copies
`frontend/dist` into `/app/frontend/dist`, which FastAPI mounts at `/`.

### The health check fails

Check Render logs for the Uvicorn startup line. The Docker command listens on
`0.0.0.0` and uses the `PORT` value supplied by Render.

### Database data disappears

In **Environment**, confirm:

```text
DATABASE_URL=sqlite:////var/data/support_agent.db
```

Also confirm the disk is mounted at `/var/data`. A database elsewhere in the
container is ephemeral.

### The browser reports failed API requests

The deployed frontend should make same-origin requests such as `/api/chat`.
Do not set `VITE_API_BASE_URL` for this single-service deployment.

### The OpenAI deployment fails at startup or chat time

Confirm that `LLM_PROVIDER=openai` and `OPENAI_API_KEY` are both present in the
Render environment. Switch `LLM_PROVIDER` back to `mock` to restore the
deterministic demo.

## 8. Remove The Deployment And Stop Charges

When the submission no longer needs to be online:

1. Open the web service's **Settings** page.
2. Delete the `loopp-customer-support-agent` service.
3. Confirm that its attached disk is also removed.
4. Check the Render billing page and Blueprint resources to make sure no paid
   service or disk remains.

Deleting the Render resources does not delete the GitHub repository.

## Render References

- [Blueprint YAML reference](https://render.com/docs/blueprint-spec)
- [Docker deployments](https://render.com/docs/docker)
- [Persistent disks](https://render.com/docs/disks)
- [Current pricing](https://render.com/pricing)

## Security Note

The app is a submission demo, not a production support system. Its customer,
refund-case, and audit endpoints do not require authentication. Use only the
included fictional seed data and do not load real customer information into a
public deployment.
