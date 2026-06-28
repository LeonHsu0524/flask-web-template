# Flask Web-Server Template

A clean, reusable Flask backend you can drop a new project on top of. It ships
seven ready-made sections — **account register, login/session, payment, VIP,
account management, per-person database sorting, and a protected external data
API** — plus configuration, tests, and CI wired up so you only change what your
project actually needs.

Everything that varies between deployments (database, secret keys, payment
credentials, deploy target, test scope) is a **setting**, not a code edit.

---

## 1. Project structure

```
app.py            # All routes + the create_app() application factory
models.py         # Database tables (SQLAlchemy)
config.py         # ALL configuration (env-driven). Edit settings here.
ecpay_payment_sdk.py   # ECPay payment SDK (third party, leave as-is)

templates/        # HTML pages (Jinja2)
static/           # Your static assets (served at /static); put images in static/images/
tests/            # Phased pytest suite (smoke / health / api / integration)

.env.example      # Copy to .env and edit for your environment
SECRETS.md        # "How to go live" checklist (real keys, DB engine, etc.)
requirements.txt  # Python dependencies
Dockerfile        # Container build (runs in production mode)
docker-compose.yml# App + nginx
nginx.conf        # Reverse proxy
Jenkinsfile       # CI/CD pipeline (host picker + test phases)
pytest.ini        # Test markers
```

### Static files & images

Drop assets in `static/` (images go in `static/images/`). Flask serves them at
`/static/...` automatically — no config needed. Reference them in templates with
`url_for`:

```html
<img src="{{ url_for('static', filename='images/logo.png') }}" alt="Logo">
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
```

Outside templates, the URL is just `/static/images/logo.png`. Image files are not
git-ignored, so they're committed with the repo.

---

## 2. Quick start (local development)

```bash
# 1. Create a virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

# 2. (Optional) create your own settings
copy .env.example .env            # Windows  (cp on macOS/Linux)

# 3. Run it
python app.py
```

Open <http://localhost:5000>. With no `.env`, it runs on sensible defaults
(SQLite, dev server, ECPay test keys). First run auto-creates the database
tables.

> **Roles:** `user` (default) < `admin` < `superadmin`.
> - **user** — sees only their own data.
> - **admin** — sees all data; manages only `user` accounts (cannot touch admins).
> - **superadmin** — full control, including creating/editing/deleting other admins.
>
> **Default admin (auto-created):** on first run the app seeds an admin account so
> a fresh deploy is never locked out. Defaults (override in `.env`):
> `username = admin`, `password = admin12345`, `role = superadmin`.
> **Change the password immediately**, set `DEFAULT_ADMIN_*` in `.env`, or
> turn it off with `DEFAULT_ADMIN_ENABLED=false`.
>
> **Create/promote more admins** any time with the bundled helper — any
> username/password you like (creates if new, promotes + resets password if it
> exists):
>
> ```bash
> python create_superadmin.py myadmin "a-strong-password"
> ```
>
> Registration via the website always creates a plain `user`; promote them from
> the account management panel.

---

## 3. Configuration — the one place you change things

All settings live in **`config.py`** and are read from environment variables
(your `.env` in dev). Pick the active profile with `APP_ENV`:

| `APP_ENV`       | Server         | Use for            |
|-----------------|----------------|--------------------|
| `development`   | Flask dev server (auto) | local coding |
| `production`    | **waitress** (Windows + Linux) | real deployment |
| `testing`       | in-memory, fast | automated tests |

### Switching the database
Edit **one line** — `DATABASE_URL` in `.env`:

```
DATABASE_URL=sqlite:///data.db                                   # default
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/mydb      # PostgreSQL
DATABASE_URL=mysql+pymysql://user:pass@host:3306/mydb            # MySQL
```

For Postgres/MySQL, uncomment the matching driver in `requirements.txt`
(`psycopg2-binary` / `PyMySQL`). See `SECRETS.md`.

### Other common settings
`SECRET_KEY`, `PORT`, `TIMEZONE`, ECPay keys, `API_KEYS`, rate limits — all in
`.env.example` with comments.

---

## 4. The application factory

The app is built by a **factory function**, so you can import it as a module
(for tests or another script) instead of running the whole system:

```python
from app import create_app
app = create_app("testing")      # build, but don't start scheduler/server
```

- `create_app(config_name)` — builds the Flask app, loads config, initializes the
  database + security extensions, registers all routes. **No side effects.**
- `init_runtime(app)` — the things you only want when actually serving: creates
  DB tables, starts the daily backup scheduler.
- `python app.py` — calls both, then starts the dev or waitress server depending
  on `APP_ENV`.

---

## 5. The seven sections & their routes

All page routes are on a blueprint named `main`, so in templates you reference
them as `url_for('main.<function>')`.

### a) Account register
| Route | Method | Purpose |
|-------|--------|---------|
| `/web_register` | GET/POST | Registration web page + submit |
| `/api/register` | POST (JSON) | Register from an app/client |
| `/register` | POST (JSON) | Minimal username+password register |

**Optional fields.** The register form can collect email, phone, a structured
address, and a birthday — each independently controlled by a pair of config flags
(`*_COLLECT_*` shows the field, `*_REQUIRED` makes it mandatory):

| Flag | Default | Effect |
|------|---------|--------|
| `REGISTER_COLLECT_EMAIL` | `true` | Show the email field |
| `REGISTER_EMAIL_REQUIRED` | `false` | Make email mandatory |
| `REGISTER_COLLECT_PHONE` | `true` | Show the phone field |
| `REGISTER_PHONE_REQUIRED` | `false` | Make phone mandatory |
| `REGISTER_COLLECT_ADDRESS` | `true` | Show the address section |
| `REGISTER_ADDRESS_REQUIRED` | `false` | Make the address mandatory |
| `REGISTER_COLLECT_BIRTHDAY` | `true` | Show the birthday field |
| `REGISTER_BIRTHDAY_REQUIRED` | `false` | Make the birthday mandatory |

The address uses **cascading dropdowns** — country → state/province worldwide
(`country-state-city`), and for Taiwan, 縣市 → 鄉鎮市區 with the **zip code
auto-filled** (`twzipcode-data`) — plus a free-text street line. The birthday uses
a native calendar picker (`<input type="date">`). Both flags apply to the web form
and the JSON `/api/register` (which accepts a nested `address` object and a
`birthday` string). The address is stored as JSON in `SystemUser.address`; the
birthday in `SystemUser.birthday`.

The dropdown data is **vendored** under `static/vendor/` (no external network at
runtime). To refresh it, re-run the vendor step in `static/vendor/README` *(see
below)*.

### b) Login / session / token
| Route | Method | Purpose |
|-------|--------|---------|
| `/login` | GET | Login web page |
| `/login` | POST (JSON) | API login → returns a **bearer token** |
| `/web_login` | POST | Web form login (sets session cookie) |
| `/logout` | GET | Clear session |
| `/forgot_password` | GET/POST | Request a reset link |
| `/reset_password/<token>` | GET/POST | Set a new password |

### c) Payment + ECPay
| Route | Method | Purpose |
|-------|--------|---------|
| `/pay_vip` | GET | Start an ECPay checkout for VIP |
| `/payment/notify` | POST | ECPay server callback (activates VIP) |
| `/payment/result` | POST | User lands here after paying |

### d) VIP
- VIP status lives on the user (`is_vip`, `vip_expires_at`), set automatically by
  `/payment/notify`. It auto-expires on the personal page.
- Admin helpers: `/admin/set_vip`, `/admin/reset_vip` (POST).

### e) Account management (admin only)
| Route | Purpose |
|-------|---------|
| `/admin/accounts` | List/search accounts |
| `/admin/create_account` | Create an account |
| `/admin/edit_account` | Edit role/email/phone/password |
| `/admin/delete_account` | Delete an account |
| `/admin/update_binding` | Bind an account to a device/product ID |

### f) Per-person database sorting
| Route | Purpose |
|-------|---------|
| `/users` | Paginated, searchable list of people (with permission filtering) |
| `/user_data/<id>/<name>` | All stored records for one person |
| `/delete_user/<id>/<name>` | Delete a person + their records |
| `/personal` | The logged-in user's own profile + records |

### g) Protected external data API
| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/v1/auth/register` | POST | — | Create an account |
| `/api/v1/auth/login` | POST | — | Log in → returns a Bearer token |
| `/api/v1/me` | GET | Bearer | The account's own profile |
| `/api/v1/me/data` | GET | Bearer | The account's own records (with payloads, paginated) |
| `/api/v1/me/data` | POST | Bearer | Store a record under the account |
| `/save` | POST | API key / Bearer | Trusted server ingestion (any identity) |
| `/log` | GET | API key / Bearer | Recent records (metadata) |

The `/api/v1` endpoints let an **outside app create an account, log in, and read/write
only its own data** — token-scoped so it can never reach another account's data. See
the next section.

---

## 6. Using the API

There are two ways in, for two kinds of caller.

### A) Self-service account API (`/api/v1`) — for an app/program

An outside app creates an account, logs in for a token, then reads/writes **only its
own data**. The token identifies the account; the server scopes every read/write to it.

```bash
# 1. Register an account
curl -X POST http://localhost:5000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"a-strong-password"}'

# 2. Log in → returns {"token": "..."}
TOKEN=$(curl -s -X POST http://localhost:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"a-strong-password"}' | jq -r .token)

# 3. POST my own data (generic JSON; optional "kind" label)
curl -X POST http://localhost:5000/api/v1/me/data \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"kind":"message","data":{"anything":"you want","values":[1,2,3]}}'

# 4. GET my own data back (paginated, with payloads)
curl http://localhost:5000/api/v1/me/data -H "Authorization: Bearer $TOKEN"

# my profile
curl http://localhost:5000/api/v1/me -H "Authorization: Bearer $TOKEN"
```

- **Isolation:** the data key is the account's unique `username` (taken from the
  verified token, never the request body) — an account can never read another's data.
- **Token revocation:** tokens carry a stamp of the password, so **changing the
  password invalidates old tokens**; they also expire after `API_TOKEN_MAX_AGE` (7d default).
- **Readable kinds:** each record has a generic `kind` label. `API_READABLE_KINDS`
  (empty = all) whitelists which kinds the API returns; `?kind=` narrows within that.
  `API_DEFAULT_KIND` is applied to writes with no kind; `API_WRITABLE_KINDS` can cap writes.
- **Pagination:** `?page` & `?per_page` (capped at `API_MAX_PAGE_SIZE`, default 200).

### B) Trusted ingestion (`/save`, `/log`) — for your own server/device

These accept a shared **API key** (`X-API-Key`, listed in `API_KEYS`) *or* a Bearer
token, and can write under any identity — for back-end pipelines you control, not
untrusted clients.

```bash
curl -X POST http://localhost:5000/save \
  -H "X-API-Key: dev-test-key-change-me" -H "Content-Type: application/json" \
  -d '{"userInfo":{"userID":"U1","name":"Alice"},"data":{"x":1},"kind":"telemetry"}'
```

Requests without a valid key/token get **401**. The stored `data` is a **generic JSON
blob** — send any shape; the template is not tied to one domain.

### Built-in protections
- **HTTPS:** always serve the API over TLS in production (the nginx config terminates
  it) — Bearer tokens and passwords must never travel in clear text.
- **CSRF:** web forms carry a CSRF token (Flask-WTF); the JSON API routes are exempt
  and use the key/token instead.
- **Rate limiting:** login, registration, `/save`, and `POST /api/v1/me/data` are
  throttled (configurable via `RATELIMIT_*` in `.env`).
- **No secret leakage:** error responses are generic; details are logged server-side.

---

## 7. Database tables (`models.py`)

| Model | Table | Notes |
|-------|-------|-------|
| `SystemUser` | `system_users` (user_db) | Login accounts, roles, VIP fields |
| `PaymentLog` | `payment_logs` (user_db) | Payment audit trail |
| `UserInfo` | `user_info` | A **person** (per-person identity): `userID`, `name`, `phone`, `device`, `time`, plus a generic `meta` JSON for extra attributes |
| `UserData` | `user_data` | One record: `data` is generic JSON + a generic `kind` label, linked to a `UserInfo` |

### Adding a column whenever you want (no rebuild)

Two ways, depending on whether you want a real column:

1. **No schema change** — just put extra fields in the JSON: `UserInfo.meta` or
   `UserData.data`. The `/save` API already drops any unknown `userInfo` keys into `meta`.

2. **Promote a field to a real, queryable column** — the schema is managed by
   **Flask-Migrate (Alembic)**, so this is a small, isolated change with no data loss:
   ```bash
   # 1. add one line to the model in models.py, e.g.:
   #      score: Mapped[int | None] = mapped_column()
   # 2. generate + apply the migration:
   flask db migrate -m "add score column"
   flask db upgrade
   ```
   On startup the app auto-applies pending migrations (`init_runtime` → `flask db upgrade`).
   To add a whole new table, add the model class and run the same two commands.

> `FLASK_APP=app.py` is needed for `flask db ...` (the app factory is auto-detected).

---

## 8. Running the tests

The suite is split into **phases** (markers) so you can run exactly what you want:

```bash
pytest -m smoke         # app boots, core pages load (fast, in-process)
pytest -m api           # register/login/token + API-key protection
pytest -m integration   # database read/write + payment helper
pytest                  # everything in-process

# health = live HTTP against a RUNNING server:
#   start the app first, then:
set TARGET_URL=http://localhost:5000   &&  pytest -m health   # Windows
```

Add tests in `tests/`, tagging each with the right `pytestmark`.

---

## 9. Deploying

Set real values in `.env` first — it is loaded automatically (`python-dotenv`).
Create it by copying the example: `cp .env.example .env` (on Windows, `copy`).
Avoid creating it with PowerShell `Out-File`/`>`, which prepends a UTF-8 BOM that
corrupts the first line; use a text editor or the copy command above.

### Option 1 — waitress behind nginx (recommended default)

1. Run the app in production mode (serves via **waitress**):
   ```bash
   APP_ENV=production python app.py          # Linux/macOS
   # set APP_ENV=production && python app.py # Windows
   ```
   In production, `TRUST_PROXY` is on, so the app honors `X-Forwarded-Proto/For`
   from nginx — HTTPS detection (Secure cookies), correct external URLs, and real
   client IPs all work.
2. Put **nginx** in front to terminate HTTPS. `nginx.conf` is a ready template:
   it redirects 80→443, terminates TLS (point `ssl_certificate*` at your certs),
   and proxies to `127.0.0.1:5000` with `X-Forwarded-Proto`. For HTTP-only local
   testing, use the commented fallback block and set `SESSION_COOKIE_SECURE=false`.

### Option 2 — Docker (optional)

`docker-compose.yml` containerizes the waitress app (binds `127.0.0.1:5000`, loads
`.env`, persists `instance/` + `backups/`). Put nginx in front the same way.
```bash
docker compose up -d --build
```

---

## 10. CI/CD with Jenkins

`Jenkinsfile` defines a parameterized pipeline. When you click **Build with
Parameters** you choose:

- **`DEPLOY_TARGET`** — which production computer to deploy to. Edit the machine
  list in the `HOST_MAP` (`environment {}` block) — `name=ssh-target` pairs.
- **`TEST_LEVEL`** — `smoke`, `health`, or `full` (which test phases to run).
- **`DEPLOY_PROD`** — whether to deploy to the chosen host after staging passes.

Stages run phase by phase: Checkout → Build & Deploy Staging → Test phases →
Shut down staging → Deploy Production (to the mapped host) → Post-deploy smoke.

---

## 11. Going live (secrets) — read `SECRETS.md`

Short version:
1. Put real values in `.env` (never commit it — it's git-ignored).
2. Swap ECPay test keys for official ones + set `PUBLIC_BASE_URL` to your domain.
3. Keep your AWS key file out of the repo; **rotate** it if it was ever committed.
4. Set a strong `SECRET_KEY` and your own `API_KEYS`.

---

## 12. How to extend it

- **Add a page/route:** add a function under the right section in `app.py`,
  decorate with `@bp.route(...)` plus `@login_required` / `@admin_required` /
  `@api_key_required` as needed, and reference it in templates with
  `url_for('main.<function>')`.
- **Protect a new API endpoint:** add `@api_key_required`.
- **Change a setting:** edit `config.py` / `.env`, not the route code.
```
