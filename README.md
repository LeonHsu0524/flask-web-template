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
static/           # CSS / images
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
> **⚠️ Change the password immediately**, or set `DEFAULT_ADMIN_*` in `.env`, or
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
> the admin panel (**帳號管理**).

---

## 3. Configuration — the one place you change things

All settings live in **`config.py`** and are read from environment variables
(your `.env` in dev). Pick the active profile with `APP_ENV`:

| `APP_ENV`       | Server         | Use for            |
|-----------------|----------------|--------------------|
| `development`   | Flask dev server (auto) | local coding |
| `production`    | **waitress** (Windows + Linux) | real deployment |
| `testing`       | in-memory, fast | automated tests |

### Switching the database (your request #4)
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

## 4. The application factory (your request #5)

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

### g) Protected external data API (your request: who/what can GET/POST)
| Route | Method | Purpose |
|-------|--------|---------|
| `/save` | POST | Receive data from an outside client |
| `/log` | GET | Recent records |

Both require authentication — see the next section.

---

## 6. Using the external API (authentication)

Protected endpoints accept **either**:

**Option A — API key** (for servers/devices). Keys are listed in `API_KEYS` in
`.env` (one per client; rotate by editing the list).

```bash
curl -X POST http://localhost:5000/save \
  -H "X-API-Key: dev-test-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"userInfo": {"userID": "U1", "name": "Alice", "phone": "0900"},
       "data": {"anything": "you want", "values": [1,2,3]}}'
```

**Option B — Bearer token** (for a logged-in app user). Get the token from
`/login`, then send it back:

```bash
# 1. login → returns {"token": "..."}
curl -X POST http://localhost:5000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret1"}'

# 2. call the API with the token
curl -X POST http://localhost:5000/save \
  -H "Authorization: Bearer <token>" \
  -d '{...}'
```

Requests without a valid key/token get **401**. The stored `data` field is a
**generic JSON blob** — send any shape; this template is not tied to one domain.

### Built-in protections
- **CSRF**: all web forms include a CSRF token (Flask-WTF). The JSON API routes
  are exempt and use the key/token instead.
- **Rate limiting**: `/login`, `/save`, `/forgot_password` are throttled
  (configurable via `RATELIMIT_*` in `.env`).

---

## 7. Database tables (`models.py`)

| Model | Table | Notes |
|-------|-------|-------|
| `SystemUser` | `system_users` (user_db) | Login accounts, roles, VIP fields |
| `PaymentLog` | `payment_logs` (user_db) | Payment audit trail |
| `UserInfo` | `user_info` | A **person** (per-person identity): `userID`, `name`, `phone`, `device`, `time`, plus a generic `meta` JSON for extra attributes |
| `UserData` | `user_data` | One record: `data` is generic JSON, linked to a `UserInfo` |

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

## 9. Production & Docker

```bash
# Production locally (uses waitress, not the dev server)
set APP_ENV=production && python app.py        # Windows

# Or with Docker (compose runs app + nginx, app already in production mode)
docker compose up -d --build
```

`nginx.conf` proxies the public port to the app. Set real values in `.env`
before deploying (see `SECRETS.md`).

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
