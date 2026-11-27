# Database Public Deployment Implementation Plan

> **For agentic workers:** Use the `superpowers:executing-plans` workflow to carry out this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the current vocabulary database app and existing SQLite data to `82.156.102.68` on HTTP port 8088, with password protection and persistent server-disk storage, without changing GitHub `master` or HippoArk.

**Architecture:** Add opt-in application-wide HTTP Basic Auth and an environment-configurable trusted-host list. Run the app as `ubuntu` under systemd on port 8088, store SQLite at `/srv/database/data/vocabulary.sqlite3`, and open only that port through UFW. Push the reviewed application version to a new `codex/` branch, never to `master`.

**Tech Stack:** FastAPI, Uvicorn, SQLite, Python 3.12, systemd, UFW, Git, SSH/SCP.

---

## File map

- Modify `app/config.py`: add optional credentials and trusted hosts; preserve current defaults.
- Modify `app/main.py`: enforce Basic Auth before every route, static file, or docs response when credentials are configured.
- Modify `.env.example`: document the optional production settings without adding real credentials.
- Modify `requirements.lock.txt`: mark the Windows-only `pywin32` package with a platform marker so Ubuntu pip skips it.
- Modify `README.md`: document public deployment configuration and HTTP demo limitation.
- Create `deploy/vocabulary.service`: the systemd unit for the server instance.
- Create `docs/superpowers/specs/2026-11-27-database-server-deployment-design.md`: approved design.
- Create `docs/superpowers/plans/2026-11-27-database-public-deploy.md`: this plan.
- Package the relevant current app changes, including `app/translate.py`, `app/fill_translations.py`, and `scripts/start_server.py`, while excluding local secrets, databases, generated workbooks, temporary outputs, and `node_modules`.

## Task 1: Add deployment configuration

**Files:** `app/config.py`, `.env.example`

- [ ] Add `app_username: str = ''`, `app_password: str = field(default='', repr=False)`, and `allowed_hosts: tuple[str, ...] = ('127.0.0.1', 'localhost', '[::1]', 'testserver')` to `Settings`.
- [ ] In `Settings.from_env()`, add this configuration parsing before `return cls(...)` and pass all three values into that constructor:

```python
app_username = os.getenv('APP_USERNAME', '')
app_password = os.getenv('APP_PASSWORD', '')
default_hosts = ('127.0.0.1', 'localhost', '[::1]', 'testserver')
raw_hosts = os.getenv('ALLOWED_HOSTS')
allowed_hosts = tuple(host.strip() for host in (raw_hosts.split(',') if raw_hosts else default_hosts) if host.strip())
if not allowed_hosts:
    raise ValueError('ALLOWED_HOSTS must contain at least one host')
```

- [ ] Pass `app_username=app_username`, `app_password=app_password`, and `allowed_hosts=allowed_hosts` as arguments to `return cls(...)`.
- [ ] Add this `Settings.__post_init__()` so direct construction also fails closed instead of silently disabling auth; reject `:` in the username because Basic Auth uses it as the credential separator:

```python
    def __post_init__(self):
        if bool(self.app_username) != bool(self.app_password):
            raise ValueError('APP_USERNAME and APP_PASSWORD must both be set or both be empty')
        if ':' in self.app_username:
            raise ValueError('APP_USERNAME must not contain a colon')
```
- [ ] Add these documented entries to `.env.example`:

```dotenv
# Optional HTTP Basic Auth; set both values to protect every app route.
APP_USERNAME=
APP_PASSWORD=
# Comma-separated host allowlist; defaults to local development hosts.
ALLOWED_HOSTS=127.0.0.1,localhost,[::1],testserver
```

- [ ] Run `git diff --check -- app/config.py .env.example` and inspect only those diffs.

## Task 2: Protect all HTTP routes

**Files:** `app/main.py`

- [ ] Import `base64`, `binascii`, and `secrets`.
- [ ] Pass `settings.allowed_hosts` to the existing `TrustedHostMiddleware`.
- [ ] Add this HTTP middleware after `app = FastAPI(...)`; it covers the index, mounted static directory, API routes, and docs. `JSONResponse` is already imported.

```python
    @app.middleware('http')
    async def authentication_boundary(request, call_next):
        if not settings.app_username and not settings.app_password:
            return await call_next(request)
        scheme, separator, token = request.headers.get('authorization', '').partition(' ')
        if not separator or scheme.lower() != 'basic':
            return JSONResponse(
                status_code=401,
                content={'detail': 'Authentication required'},
                headers={'WWW-Authenticate': 'Basic realm="Vocabulary"'},
            )
        try:
            decoded = base64.b64decode(token, validate=True).decode('utf-8')
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded = ''
        supplied_username, delimiter, supplied_password = decoded.partition(':')
        valid = delimiter and secrets.compare_digest(
            supplied_username.encode('utf-8'), settings.app_username.encode('utf-8')
        ) and secrets.compare_digest(
            supplied_password.encode('utf-8'), settings.app_password.encode('utf-8')
        )
        if not valid:
            return JSONResponse(
                status_code=401,
                content={'detail': 'Authentication required'},
                headers={'WWW-Authenticate': 'Basic realm="Vocabulary"'},
            )
        return await call_next(request)
```

- [ ] Keep the existing same-origin write middleware in place. Do not add CORS or change API route contracts.
- [ ] Run `git diff --check -- app/main.py` and inspect the changes.

## Task 3: Document and package the service

**Files:** `deploy/vocabulary.service`, `README.md`

- [ ] Create `deploy/vocabulary.service` with this content:

```ini
[Unit]
Description=Personal Vocabulary Database
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/srv/database/app
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/database/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

- [ ] Add this README section after “Model and runtime configuration”:

```markdown
## Server demo

The server demo keeps its SQLite database at `/srv/database/data/vocabulary.sqlite3`. Its server-only `.env` sets `DATABASE_PATH`, `APP_USERNAME`, `APP_PASSWORD`, and `ALLOWED_HOSTS=82.156.102.68`. Keep the `.env` private and out of Git. The public demo uses HTTP on port 8088; its generated password is for this demo only because HTTP does not encrypt credentials or traffic.
```

- [ ] Ensure the README does not contain the real key or generated password.
- [ ] Run `git diff --check -- README.md deploy/vocabulary.service` and inspect the changes.

## Task 4: Review and commit the new version locally

**Files:** intended app and documentation changes only.

- [ ] Review all current diffs in `README.md`, `app/`, `docs/system-design.md`, `tests/test_api.py`, and `tests/test_learning.py`; these are existing local work that belongs to the version being deployed.
- [ ] Add the required untracked app files `app/fill_translations.py`, `app/translate.py`, and `scripts/start_server.py`.
- [ ] Do not stage `version control/v0.2/v0.2.xlsx`, `DatabaseEvidenceLog_completed.xlsx`, `DatabaseEvidenceLog_filled.xlsx`, `~$DatabaseEvidenceLog_completed.xlsx`, `scripts/render_final_evidence_qa.mjs`, `scripts/tune_evidence_package.mjs`, `tmp/`, `.env`, `data/`, or any log file.
- [ ] Stage only the reviewed app, static assets, README, design/plan documents, and `deploy/vocabulary.service`.
- [ ] Use this explicit staging command so unrelated generated files and the edited historical workbook remain unstaged:

```powershell
git add -- README.md .env.example requirements.lock.txt app/agent.py app/config.py app/db.py app/deepseek.py app/dictionary.py app/fill_translations.py app/learning.py app/main.py app/mcp_server.py app/repository.py app/schemas.py app/translate.py app/static/app.js app/static/index.html app/static/styles.css docs/system-design.md docs/superpowers/specs/2026-11-27-database-server-deployment-design.md docs/superpowers/plans/2026-11-27-database-public-deploy.md tests/test_api.py tests/test_learning.py scripts/start_server.py deploy/vocabulary.service
```

- [ ] Run `git diff --cached --check`; commit as `feat: deploy vocabulary app with protected public access`.
- [ ] Commit and push with:

```powershell
git commit -m "feat: deploy vocabulary app with protected public access"
git push --set-upstream origin codex/database-public-deploy
git ls-remote origin refs/heads/master refs/heads/codex/database-public-deploy
```

- [ ] Run `git status --short --branch` and confirm no secret or database file is staged.
- [ ] Verify `origin/master` still resolves to the original `5027d18` commit. If branch push is rejected, retain the local branch and deploy its local archive instead.

## Task 5: Create safe deployment artifacts

**Files:** temporary files under the ignored local `tmp/` directory only.

- [ ] Use Python's SQLite backup API to make a consistent snapshot of `data/vocabulary.sqlite3` at `tmp/vocabulary-server-seed.sqlite3`; do not copy the live file directly or change the local database:

```powershell
@'
import sqlite3
source = sqlite3.connect('file:data/vocabulary.sqlite3?mode=ro', uri=True)
target = sqlite3.connect('tmp/vocabulary-server-seed.sqlite3')
try:
    source.backup(target)
finally:
    target.close()
    source.close()
'@ | & .\.venv\Scripts\python.exe -
```

- [ ] Verify the snapshot has `PRAGMA user_version=2`, 79 rows in `words`, and 3 rows in `review_events`.
- [ ] Verify the snapshot counts without printing vocabulary content:

```powershell
& .\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('tmp/vocabulary-server-seed.sqlite3'); print('schema',c.execute('pragma user_version').fetchone()[0],'words',c.execute('select count(*) from words').fetchone()[0],'reviews',c.execute('select count(*) from review_events').fetchone()[0]); c.close()"
```

- [ ] Create the committed source archive and verify its contents:

```powershell
git archive --format=zip --output=tmp/database-deploy.zip HEAD
& .\.venv\Scripts\python.exe -c "import zipfile; n=zipfile.ZipFile('tmp/database-deploy.zip').namelist(); assert any(x.startswith('app/static/') for x in n) and 'deploy/vocabulary.service' in n and 'requirements.lock.txt' in n; assert not any(x == '.env' or x.startswith('data/') or '/logs/' in x or x.startswith('DatabaseEvidenceLog') or x.startswith('tmp/') for x in n); print('archive-ok',len(n))"
```

- [ ] Generate a 24-character ASCII demo password into a PowerShell variable without echoing it:

```powershell
$demoPassword = & .\.venv\Scripts\python.exe -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"
```

- [ ] Package the installed spaCy model and its metadata as a portable wheel because GitHub model downloads from the server are stalled:

```powershell
@'
from pathlib import Path
import zipfile
base = Path('.venv/Lib/site-packages')
roots = [base / 'en_core_web_sm', base / 'en_core_web_sm-3.8.0.dist-info']
out = Path('tmp/en_core_web_sm-3.8.0-py3-none-any.whl')
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for root in roots:
        if not root.exists():
            raise SystemExit(f'missing model path: {root.name}')
        for path in root.rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(base).as_posix())
'@ | & .\.venv\Scripts\python.exe -
```

## Task 6: Install on the server

**Target:** `/srv/database/app` and `/srv/database/data` on `txy`.

- [ ] Before creating files, check that the resolved paths `/srv/database/app` and `/srv/database/data` are safe deployment targets and do not contain an existing deployment. If an existing database is present, preserve it and do not overwrite it with the local snapshot.
- [ ] Create `/srv/database/app`, `/srv/database/data`, and `/srv/database/app/logs`, owned by `ubuntu`; set directory permissions to owner-only where practical.
- [ ] Create only the application and data directories after confirming there is no existing deployment at those exact paths. The command does not recursively change ownership of `/srv/database` or any unrelated directory:

```powershell
ssh txy "sudo -n test ! -e /srv/database/app && sudo -n test ! -e /srv/database/data"
ssh txy "sudo -n install -d -o ubuntu -g ubuntu -m 750 /srv/database/app /srv/database/data /srv/database/app/logs"
```

- [ ] Build the server `.env` in memory from the local `.env`; preserve every setting except replace `DATABASE_PATH` and add the three deployment settings. Stream it over SSH without printing it or modifying the local `.env`:

```powershell
$serverEnv = @(Get-Content -LiteralPath .env | Where-Object { $_ -notmatch '^\s*(DATABASE_PATH|APP_USERNAME|APP_PASSWORD|ALLOWED_HOSTS)\s*=' })
$serverEnv += 'DATABASE_PATH=/srv/database/data/vocabulary.sqlite3'
$serverEnv += 'APP_USERNAME=demo'
$serverEnv += "APP_PASSWORD=$demoPassword"
$serverEnv += 'ALLOWED_HOSTS=82.156.102.68'
$serverEnv | ssh txy "umask 077; cat > /srv/database/app/.env; chmod 600 /srv/database/app/.env"
```

- [ ] Upload and unpack the app. Seed SQLite only if it is not already present:

```powershell
scp tmp/database-deploy.zip txy:/tmp/database-deploy.zip
scp tmp/vocabulary-server-seed.sqlite3 txy:/srv/database/data/vocabulary-server-seed.sqlite3
ssh txy "python3 -m zipfile -e /tmp/database-deploy.zip /srv/database/app && chmod 700 /srv/database/data && if [ ! -e /srv/database/data/vocabulary.sqlite3 ]; then install -o ubuntu -g ubuntu -m 600 /srv/database/data/vocabulary-server-seed.sqlite3 /srv/database/data/vocabulary.sqlite3; fi && chmod 600 /srv/database/app/.env /srv/database/data/vocabulary-server-seed.sqlite3"
```

- [ ] Set the server `.env` to owner `ubuntu`, group `ubuntu`, mode `0600`; set the SQLite database and containing data directory to owner `ubuntu` and restrictive permissions.
- [ ] Create a Python 3.12 virtual environment, install the locked dependencies except the GitHub-hosted spaCy model, then install the local model wheel:

```powershell
scp tmp/en_core_web_sm-3.8.0-py3-none-any.whl txy:/tmp/en_core_web_sm-3.8.0-py3-none-any.whl
ssh txy "set -e; python3 -m venv /srv/database/app/.venv; grep -v '^en_core_web_sm @' /srv/database/app/requirements.lock.txt > /tmp/vocabulary-requirements.txt; cd /srv/database/app; .venv/bin/python -m pip install -r /tmp/vocabulary-requirements.txt; .venv/bin/python -m pip install /tmp/en_core_web_sm-3.8.0-py3-none-any.whl; .venv/bin/python -c 'import spacy; nlp=spacy.load(\"en_core_web_sm\"); print(\"spacy-model\",nlp.meta[\"version\"])'"
```

- [ ] Install `deploy/vocabulary.service` as `/etc/systemd/system/vocabulary.service`; run `systemctl daemon-reload` and enable/start only `vocabulary.service`.
- [ ] Install and start only the new service:

```powershell
ssh txy "sudo -n install -o root -g root -m 644 /srv/database/app/deploy/vocabulary.service /etc/systemd/system/vocabulary.service && sudo -n systemctl daemon-reload && sudo -n systemctl enable --now vocabulary.service"
```

- [ ] Allow `8088/tcp` through UFW. Do not edit Nginx config, stop other services, or touch HippoArk.
- [ ] Add only the new port to UFW:

```powershell
ssh txy "sudo -n ufw allow 8088/tcp comment 'Vocabulary demo HTTP'"
```
- [ ] Inspect `systemctl status vocabulary.service`, `ss -ltnp`, and `free -h`; if available memory remains healthy, leave Vibe-Trading and Neuromesh running.

## Task 7: Verify the public site

- [ ] From PowerShell, confirm the site challenges unauthenticated users, then request the protected health and word count endpoints with the generated credentials. Print only status and counts:

```powershell
$baseUrl = 'http://82.156.102.68:8088'
try { (Invoke-WebRequest "$baseUrl/" -TimeoutSec 20).StatusCode } catch { $_.Exception.Response.StatusCode.value__ }
$pair = [Text.Encoding]::ASCII.GetBytes("demo:$demoPassword")
$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String($pair) }
(Invoke-WebRequest "$baseUrl/" -Headers $headers -TimeoutSec 20).StatusCode
$health = Invoke-RestMethod "$baseUrl/api/health" -Headers $headers -TimeoutSec 20
$rows = Invoke-RestMethod "$baseUrl/api/words/all?limit=1000" -Headers $headers -TimeoutSec 20
"health=$($health.status) model_configured=$($health.model_configured) words=$($rows.Count)"
```

- [ ] Confirm `/api/health` returns `ok`, the word endpoint returns 79 entries, and the HTTP response does not contain the model key.
- [ ] Verify the server-side SQLite file exists at `/srv/database/data/vocabulary.sqlite3` and contains 79 words.
- [ ] If port 8088 is blocked outside despite the UFW rule, stop only `vocabulary.service`, bind it to loopback, and start an independent Cloudflare Quick Tunnel to it. Do not alter HippoArk's tunnel or listeners.
- [ ] Report the working public URL, the generated username/password, the new branch URL if pushed, and whether existing services remained running.

## Scope and verification notes

- Do not run pytest or add tests in this task. The user requested deployment; verification is limited to compilation, configuration checks, and HTTP/database smoke checks.
- Do not stop Vibe-Trading or Neuromesh unless actual memory pressure requires it; never stop or reconfigure HippoArk.
- Keep all existing server data after the initial seed. Future deploys must not replace `/srv/database/data/vocabulary.sqlite3`.

## Plan self-review

- Every requested behavior maps to a task: local code, server-disk storage, shared LLM environment, a public URL, a new Git branch, and preservation of HippoArk.
- No secret is included in Git, stdout, the service unit, or deployment documentation.
- The auth settings are optional by default, so the local application continues to work as it does now.
- All post-initialization deployment steps preserve the server database rather than copying the local database over it.
