# Deploying to Render

The deployment has three parts on Render, plus one on the Hugging Face Hub:

| Part | Where | Notes |
|---|---|---|
| Database | Render Postgres | Created by the blueprint |
| API | Render web service built from `Dockerfile` | Created by the blueprint |
| Web app | Render static site built from `frontend/` | Created by the blueprint |
| Trained models | A private model repository on the **Hugging Face Hub** | Free. Render wipes a service's disk on every deploy and restart, so the models can't live there. The API downloads a model the first time it needs it (`backend/ml/store.py`). Each model is about 4 MB |

`render.yaml` in the project root describes the three Render parts.

## 1. Hugging Face (models)

1. Create a free account at https://huggingface.co.
2. Go to **Settings → Access Tokens** and create two tokens:
   - a **Write** token, used on your computer to upload models;
   - a **Read** token, used by Render to download them.
3. Pick a repository name such as `your-username/hardship-models`. You don't
   need to create it: the first upload creates it as **private**.

## 2. Render (blueprint)

1. In the Render dashboard, choose **New → Blueprint** and connect the GitHub
   repository `tecGrwLtd/household_hardship`.
2. Render reads `render.yaml` and asks for the values it can't generate:

   | Setting | Service | Value |
   |---|---|---|
   | `HARDSHIP_ADMIN_PASSWORD` | hardship-api | The admin password, at least 10 characters |
   | `HARDSHIP_MODEL_REPO` | hardship-api | `your-username/hardship-models` |
   | `HF_TOKEN` | hardship-api | The Hugging Face **Read** token |
   | `HARDSHIP_CORS_ORIGINS` | hardship-api | The web app's address, normally `https://hardship-web.onrender.com` |
   | `VITE_API_BASE` | hardship-web | The API's address, normally `https://hardship-api.onrender.com` |

   `HARDSHIP_SECRET`, which signs sign-in tokens, is generated for you.
3. Apply the blueprint. The API's first deploy **fails** because the database
   is still empty. That's expected: the next step fixes it.

If Render gives a service a different address (for example with a suffix,
when the name is taken), correct `HARDSHIP_CORS_ORIGINS` and `VITE_API_BASE`
afterwards. The web app reads `VITE_API_BASE` when it is built, so redeploy
the web app after changing it.

## 3. Fill the database (once, from your computer)

On the Render database's page, copy its **External Database URL**. Then, in
the project folder, with the virtual environment set up (`pip install -r
requirements.txt`):

```bash
# Git Bash / macOS / Linux
HARDSHIP_MODEL_REPO=your-username/hardship-models HF_TOKEN=<write token> \
  python db/setup_database.py --dsn "<external database URL>" --train
```

```powershell
# PowerShell
$env:HARDSHIP_MODEL_REPO = "your-username/hardship-models"; $env:HF_TOKEN = "<write token>"
python db/setup_database.py --dsn "<external database URL>" --train
```

The script takes about a minute and does the following:

1. Creates the tables and views.
2. Loads the sample data.
3. Trains the need and repeat models, uploads them to Hugging Face and
   activates them.
4. Scores every application.
5. Writes the repeat forecasts and a drift report.

Leave out `--train` to start with the rule-based placeholder model. On a
database that already has the tables, the script only applies the
migrations.

Then, on Render, open **hardship-api → Manual Deploy → Deploy latest commit**.
When it's live, open the web app and sign in as `admin` with the password you
set.

## 4. After the first deploy

- **Demo caseworker:** the sample data includes the account `uwase` with the
  development password `caseworker-dev-only`. In **Admin console →
  Accounts**, change its password or deactivate it before sharing the
  address.
- **Retraining:** run `python -m backend.ml --dsn "<external URL>" train`
  with the same two variables set. The new version is uploaded and appears in
  **Models & monitoring → Model cards**; activate it there.
- **Secrets:** keep the External Database URL and the Write token to
  yourself. Anyone with either can change the data or the models.

## Free-tier limits

These were Render's terms at the time of writing; check render.com/pricing.

- **Idle API:** free web services go to sleep after about 15 minutes idle.
  The first visit after that takes up to a minute while the API wakes up and
  downloads the active model. Open the app a minute before a demo, or use a
  paid instance for the API.
- **Free database expiry:** free Postgres databases expire after about a
  month. To move on, create a new one, point `HARDSHIP_DSN` at it (the
  blueprint does this if you recreate it with the same name), and run step 3
  again. The models already on Hugging Face stay there.
- **Static site:** the web app is a static site and never sleeps.
