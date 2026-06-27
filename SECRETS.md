# Secrets & "HOW TO GO LIVE" checklist

All sensitive/config values are read from environment variables (see
`config.py`). In development they fall back to **test** values so the app runs
out of the box. Copy `.env.example` → `.env` and edit before deploying.

> The real `.env` and `AWS-KEY.pem` are git-ignored. Never commit them.

---

## 1. ECPay payment credentials

The defaults are ECPay's official public **sandbox** credentials (merchant
`2000132`), paired with the sandbox action URL, so test checkout works out of the
box. To accept real payments:

1. Get your official `MerchantID`, `HashKey`, `HashIV` from the ECPay merchant
   portal (https://vendor.ecpay.com.tw/).
2. Set in `.env`:
   ```
   ECPAY_MERCHANT_ID=<official id>
   ECPAY_HASH_KEY=<official key>
   ECPAY_HASH_IV=<official iv>
   ECPAY_ACTION_URL=https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5
   PUBLIC_BASE_URL=https://your-public-domain
   ```
3. `PUBLIC_BASE_URL` must be reachable from the internet (domain or ngrok) so
   ECPay can POST to `/payment/notify` and `/payment/result`.

| Environment | MerchantID / HashKey / HashIV | Action URL |
|-------------|-------------------------------|------------|
| Sandbox (default) | `2000132` / `5294y06JbISpM5x9` / `v77hoKGq4kWxNNIS` | `https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5` |
| Production | your official credentials | `https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5` |

> **Important:** the MerchantID and the action URL must belong to the **same**
> environment. Mixing them — e.g. a production MerchantID against the sandbox URL —
> fails with `10200074 找不到加密金鑰` (encryption key not found).

## 2. AWS key file (`AWS-KEY.pem`)

The repo previously shipped a private key in source control — **do not do this**.

1. Keep the real `AWS-KEY.pem` outside the repo (it is git-ignored and
   docker-ignored).
2. Point to it via an env var / your deploy tooling rather than committing it.
3. If the old key was ever pushed, **rotate it** in AWS. Starting a fresh repo
   (no old `.git` history) ensures the old leaked key is not carried forward.

## 3. Flask secret key

```
SECRET_KEY=<long random string>
```
Used for sessions and for signing password-reset / API login tokens. Changing
it invalidates existing sessions and tokens.

## 4. External data API keys

`/save` and `/log` require either:
- an `X-API-Key` header matching one of `API_KEYS`, or
- an `Authorization: Bearer <token>` issued by `/login`.

```
API_KEYS=client-a-key,client-b-key
```
Give each external client its own key; rotate by editing the list.

## 4b. Default admin account

On first run the app auto-creates an admin so a fresh deploy isn't locked out:

```
DEFAULT_ADMIN_ENABLED=true
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin12345   # <-- CHANGE THIS
DEFAULT_ADMIN_ROLE=superadmin
```

- It is created **only if** that username doesn't already exist (it never
  overwrites an existing account or resets its password).
- **Change the default password before deploying**, or set your own in `.env`.
- After you've created your real admin, set `DEFAULT_ADMIN_ENABLED=false`.
- To add more admins later: `python create_superadmin.py <username> <password>`.

## 5. Switching the database engine

Edit `DATABASE_URL` in `.env`:

| Engine     | Example URL                                             | Extra driver (requirements.txt) |
|------------|--------------------------------------------------------|---------------------------------|
| SQLite     | `sqlite:///data.db`                                     | (built in)                      |
| PostgreSQL | `postgresql+psycopg2://user:pass@host:5432/dbname`     | `psycopg2-binary`               |
| MySQL      | `mysql+pymysql://user:pass@host:3306/dbname`           | `PyMySQL`                       |

Uncomment the matching driver in `requirements.txt` and reinstall.

## 6. Production server

`APP_ENV=production` makes `app.py` serve via **waitress** (works on Windows and
Linux). The Docker image sets this automatically. Behind nginx, no extra change
is needed (`nginx.conf` proxies to the app).

## 7. Email (optional SMTP for password-reset links)

If `SMTP_HOST` is blank, the password-reset flow just **logs** the reset link
(dev). To actually email it, set in `.env`:

```
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASSWORD=app-password
SMTP_FROM=you@example.com
SMTP_USE_TLS=true
```

## 8. Production hardening checklist

- `SECRET_KEY` — set a long random value (app warns at startup if left default).
- `DEFAULT_ADMIN_PASSWORD` — change it, or set `DEFAULT_ADMIN_ENABLED=false`
  after you've created your own admin (app warns if left default).
- `SESSION_COOKIE_SECURE=true` — required when served over HTTPS (default on in
  `ProductionConfig`).
- `ECPAY_ACTION_URL` — defaults to the **sandbox**; switch to live + set real
  ECPay credentials (§1) only when going live.
- `RATELIMIT_STORAGE_URI` — use `redis://…` if running multiple workers.
