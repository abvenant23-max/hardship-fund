# Deploying to Render

The online setup has three parts, all on free tiers:

| Part | Where | Notes |
|---|---|---|
| Web app + API | One **Render** web service, built from `deploy/web.Dockerfile` | The app is at `/` and the API at `/api` (docs at `/api/docs`). It uses about 175 MB of the free 512 MB |
| Database | **Render** Postgres, created by the blueprint | You can use Neon instead; see the free-tier limits below |
| Trained models | A **private** Hugging Face model repository | Render wipes the service's disk on every deploy and restart, so the app downloads the active model the first time it needs it (`backend/ml/store.py`). Each model is about 4 MB. Model repositories are free on any Hugging Face account |

`render.yaml` in the project root describes the Render parts.

## 1. Hugging Face (models)

1. Create a free account at https://huggingface.co.
2. Go to **Settings → Access Tokens** and create two tokens:
   - a **Write** token, used on your computer to upload models;
   - a **Read** token, used by Render to download them.
3. Pick a repository name such as `your-username/hardship-models`. You don't
   need to create it: the first upload creates it as **private**.

## 2. Render (blueprint)

1. In the Render dashboard, choose **New → Blueprint** and connect the GitHub
   repository.
2. Render reads `render.yaml` and asks for three values:

   | Setting | Value |
   |---|---|
   | `HARDSHIP_ADMIN_PASSWORD` | The admin password, at least 10 characters |
   | `HARDSHIP_MODEL_REPO` | `your-username/hardship-models` |
   | `HF_TOKEN` | The Hugging Face **Read** token |

   The token secret (`HARDSHIP_SECRET`) is generated for you, and
   `HARDSHIP_DSN` is wired to the new database.
3. Apply the blueprint. The web service's first deploy **fails** because the
   database is still empty. That's expected: the next step fixes it.

## 3. Fill the database (once, from your computer)

On the Render database's page, copy its **External Database URL**. Then, in
the project folder, with the virtual environment set up (`pip install -r
requirements.txt`):

```powershell
# PowerShell
$env:HARDSHIP_MODEL_REPO = "your-username/hardship-models"; $env:HF_TOKEN = "<write token>"
python db/setup_database.py --dsn "<External Database URL>" --train
```

```bash
# Git Bash / macOS / Linux
HARDSHIP_MODEL_REPO=your-username/hardship-models HF_TOKEN=<write token> \
  python db/setup_database.py --dsn "<External Database URL>" --train
```

The script takes about a minute and does the following:

1. Creates the tables and views.
2. Loads the sample data.
3. Trains the need and repeat models, uploads them to the model repository
   and activates them.
4. Scores every application.
5. Writes the repeat forecasts and a drift report.

Leave out `--train` to start with the rule-based placeholder model. On a
database that already has the tables, the script only applies the
migrations.

Then, on Render, open the **hardship-fund** service and choose **Manual
Deploy → Deploy latest commit**. When it's live, open its address (shown at
the top, e.g. `https://hardship-fund.onrender.com`) and sign in as `admin`
with the password you set.

Every push to the repository's `main` branch redeploys the service
automatically.

## 4. After the first deploy

- **Demo caseworker:** the sample data includes the account `uwase` with the
  development password `caseworker-dev-only`. In **Admin console →
  Accounts**, change its password or deactivate it before sharing the
  address.
- **Retraining:** run `python -m backend.ml --dsn "<External URL>" train`
  with the two variables from step 3 set. The new version is uploaded and
  appears in **Models & monitoring → Model cards**; activate it there.
- **Secrets:** keep the External Database URL and the Write token to
  yourself. Anyone with either can change the data or the models.

## Free-tier limits

These were Render's terms at the time of writing; check render.com/pricing.

- **Sleep:** a free web service goes to sleep after about 15 minutes idle.
  The first visit after that takes up to a minute while the app wakes up and
  downloads the active model. Open the app a minute before a demo.
- **Database expiry:** a free Render Postgres database expires after about a
  month. To avoid that, use **Neon** (https://neon.tech: free, pauses when
  idle but doesn't expire). Create a Neon project on Postgres 16, run step 3
  with its connection string (the direct one, pooling off), and in the
  Render service's **Environment** tab set `HARDSHIP_DSN` to that string.
  You can then delete the Render database. The models on Hugging Face stay
  where they are.

## Trying the Render image locally

```bash
docker build -f deploy/web.Dockerfile -t hardship-web .
docker run -p 10000:10000 -e PORT=10000 -e HARDSHIP_DSN=... -e HARDSHIP_SECRET=... \
  -e HARDSHIP_ADMIN_PASSWORD=... hardship-web          # http://localhost:10000
```

## Alternative: Hugging Face Space (paid)

`space/` and `deploy/push_space.py` publish the same app as a Hugging Face
Space: the Gradio SDK is used as a plain Python runtime that starts
`backend/web.py`. Hugging Face now requires a PRO plan to create a Gradio or
Docker Space (their Spaces overview, checked 28 Sep 2026), so this is only
worth it with a PRO account. To use it:

1. Fill a database as in step 3. Neon works well here.
2. Run `python deploy/push_space.py --space your-username/hardship-fund`
   with a Write token in `HF_TOKEN`. This needs Node.js 20+, because the web
   app is built on your computer.
3. In the Space's **Settings → Variables and secrets**, add these secrets:
   `HARDSHIP_DSN`, `HARDSHIP_SECRET`, `HARDSHIP_ADMIN_PASSWORD`,
   `HARDSHIP_MODEL_REPO` and `HF_TOKEN`. Then restart the Space.

`.github/workflows/space.yml` republishes the Space on every push once the
repository has an `HF_TOKEN` secret and an `HF_SPACE` variable. Without
them, it does nothing.
