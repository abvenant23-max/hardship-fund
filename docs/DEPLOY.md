# Deploying to Hugging Face Spaces + Neon

The online setup has three parts, all on free tiers:

| Part | Where | Notes |
|---|---|---|
| Web app + API | A public **Hugging Face Space** on the free **Gradio** SDK and **CPU basic** hardware, at `https://<owner>-<name>.hf.space` | The Gradio SDK is only used as a Python runtime. `space/app.py` starts our own FastAPI server, with the app at `/` and the API at `/api` (docs at `/api/docs`). Docker Spaces aren't free for every account, so we don't use one |
| Database | **Neon** Postgres | Our data is about 20 MB |
| Trained models | A **private** Hugging Face model repository | The Space's disk is wiped on every restart, so the API downloads the active model the first time it needs it (`backend/ml/store.py`). Each model is about 4 MB |

The Space is public, so a client can open it without an account. The app
still requires sign-in. The Space page shows the application code, but none
of the data, secrets or models: those live in Neon, the Space's secrets and
the private model repository.

## 1. Accounts and tokens

1. **Hugging Face:** create a free account at https://huggingface.co. Under
   **Settings → Access Tokens**, create a **Write** token. It's used to
   upload models and publish the Space, from your computer and from GitHub.
   For the Space itself, create a fine-grained token that can only **read**
   the model repository. If that's fiddly, a Read token works too.
2. **Neon:** create a free account at https://neon.tech and a project on
   Postgres 16, in the region nearest your users. On the project dashboard,
   choose **Connect** and copy the connection string. Use the **direct** one
   (pooling off). It looks like
   `postgresql://user:password@ep-....neon.tech/neondb?sslmode=require`.

Pick two names:

- the model repository, e.g. `your-username/hardship-models` (created
  private on first upload);
- the Space, e.g. `your-username/hardship-fund` (created on first publish).

## 2. Fill the database (once, from your computer)

In the project folder, with the virtual environment set up (`pip install -r
requirements.txt`):

```powershell
# PowerShell
$env:HARDSHIP_MODEL_REPO = "your-username/hardship-models"; $env:HF_TOKEN = "<write token>"
python db/setup_database.py --dsn "<Neon connection string>" --train
```

```bash
# Git Bash / macOS / Linux
HARDSHIP_MODEL_REPO=your-username/hardship-models HF_TOKEN=<write token> \
  python db/setup_database.py --dsn "<Neon connection string>" --train
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

## 3. Publish the Space

You don't have to create the Space by hand: the script creates it on its
first run as a public **Gradio** Space on free **CPU basic** hardware. If you
prefer to create it on the website (**New Space**), choose:

- SDK: **Gradio**, template **Blank**;
- hardware: **CPU basic · Free**;
- visibility: **Public**.

Keep the name the same as the one you pass to the script.

The script needs Node.js 20 or newer, because it builds the web app on your
computer: Gradio Spaces can't build it themselves.

```powershell
python deploy/push_space.py --space your-username/hardship-fund    # HF_TOKEN still set from step 2
```

It builds the web app and uploads:

- `backend/`;
- the built app as `web/`;
- `requirements.txt`;
- `space/app.py`, `space/packages.txt` and `space/README.md`, placed at the
  Space's root.

Add `--dry-run` to list the files without uploading anything.

On the Space's page, open **Settings → Variables and secrets** and add these
**secrets**:

| Secret | Value |
|---|---|
| `HARDSHIP_DSN` | The Neon connection string |
| `HARDSHIP_SECRET` | A long random string that signs sign-in tokens, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `HARDSHIP_ADMIN_PASSWORD` | The admin password, at least 10 characters |
| `HARDSHIP_MODEL_REPO` | `your-username/hardship-models` |
| `HF_TOKEN` | The token that can read the model repository |

Then choose **Restart this Space** (in Settings, or the **⋮** menu). The
first start takes a few minutes while the Space installs the Python
packages. When the status shows **Running**, open
`https://your-username-hardship-fund.hf.space` and sign in as `admin` with
your password.

## 4. Deploy on every push (optional)

`.github/workflows/space.yml` republishes the Space on every push to `main`.
To enable it, open the GitHub repository's **Settings → Secrets and
variables → Actions** and add:

- the secret `HF_TOKEN`: the Write token;
- the variable `HF_SPACE`: `your-username/hardship-fund`.

Without them, the workflow is skipped. You can also run it by hand from the
**Actions** tab.

## 5. After the first deploy

- **Demo caseworker:** the sample data includes the account `uwase` with the
  development password `caseworker-dev-only`. In **Admin console →
  Accounts**, change its password or deactivate it before sharing the
  address.
- **Retraining:** run `python -m backend.ml --dsn "<Neon string>" train`
  with the two variables from step 2 set. The new version is uploaded and
  appears in **Models & monitoring → Model cards**; activate it there.
- **Secrets:** keep the Neon connection string and the Write token to
  yourself. Anyone with either can change the data, the models or the app.

## Free-tier limits

These are the terms as we understood them in September 2026; check each
site.

- **Space sleep:** a free Space sleeps after about 48 hours without visitors.
  The next visit wakes it in a minute or two, including downloading the
  active model. Open it a few minutes before a demo.
- **Neon pause:** Neon pauses the database when it's idle and wakes it in
  about a second on the next query. It doesn't expire. The free storage is
  about 0.5 GB.
- **Space storage:** the Space's disk is temporary. Nothing the app needs
  lives there: data is in Neon and models are in the model repository.

## Trying the Space locally

To check a change before publishing:

```bash
python deploy/push_space.py --stage-only space-build     # builds the web app, writes the Space's files
cd space-build && pip install -r requirements.txt
HARDSHIP_DSN=... HARDSHIP_SECRET=... HARDSHIP_ADMIN_PASSWORD=... python app.py   # http://localhost:7860
```

`space-build/` is git-ignored.
