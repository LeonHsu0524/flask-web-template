"""
Reusable Flask web-server template.

Sections kept (see README): account register, login/session, payment + ECPay,
VIP, account management, per-person database sorting, and a protected external
data API. All configuration lives in config.py (env-driven). The app is built
with an application factory (create_app) so it can be imported as a module and
tested, not only run as a whole system.
"""
import logging
import os
import shutil
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from zoneinfo import ZoneInfo

# Third-party
import ecpay_payment_sdk
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask_migrate import Migrate, upgrade as migrate_upgrade
from flask import (
    Blueprint,
    Flask,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import URLSafeTimedSerializer, BadData
from sqlalchemy import or_

from config import get_config
from models import PaymentLog, SystemUser, UserData, UserInfo, db

# ---------------------------------------------------------------------------
# Optional security extensions (gracefully degrade if not installed so the
# template always runs; install them via requirements.txt for full protection).
# ---------------------------------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _HAS_LIMITER = True
except Exception:  # pragma: no cover
    _HAS_LIMITER = False

try:
    from flask_wtf import CSRFProtect
    _HAS_CSRF = True
except Exception:  # pragma: no cover
    _HAS_CSRF = False


class _NoopExt:
    """Stand-in for a missing extension: every call is a harmless no-op."""

    def init_app(self, app):
        pass

    def limit(self, *a, **k):
        def deco(f):
            return f
        return deco

    def exempt(self, f):
        return f


if _HAS_LIMITER:
    limiter = Limiter(key_func=get_remote_address)
else:  # pragma: no cover
    limiter = _NoopExt()

csrf = CSRFProtect() if _HAS_CSRF else _NoopExt()
migrate = Migrate()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def get_now() -> datetime:
    return datetime.now(ZoneInfo(current_app.config["TIMEZONE"]))


def to_local(dt: datetime) -> datetime:
    """Normalize any datetime to the configured local timezone."""
    if dt is None:
        return dt
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


# ---------------------------------------------------------------------------
# Auth / protection
# ---------------------------------------------------------------------------
def login_required(f):
    """Browser/session auth for the web pages."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.web_login_page"))
        return f(*args, **kwargs)
    return decorated


# Role model: 'user' < 'admin' < 'superadmin'.
ADMIN_ROLES = ("admin", "superadmin")
ELEVATED_ROLES = ("admin", "superadmin")  # accounts only a superadmin may manage


def can_manage(actor, target=None, new_role=None) -> bool:
    """
    Whether 'actor' may manage a target account / assign a role.
    - superadmin: may do anything.
    - admin: may only manage plain 'user' accounts, and may not grant admin/superadmin.
    """
    if actor.role == "superadmin":
        return True
    if target is not None and target.role in ELEVATED_ROLES:
        return False
    if new_role in ELEVATED_ROLES:
        return False
    return True


def admin_required(f):
    """Web auth + admin (or superadmin) role for the account-management pages."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.web_login_page"))
        user = db.session.get(SystemUser, session["user_id"])
        if not user or user.role not in ADMIN_ROLES:
            return "權限不足 (Permission Denied)", 403
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def api_key_required(f):
    """
    Protects the external data API. Accepts EITHER:
      - an X-API-Key header matching one of config API_KEYS, OR
      - an Authorization: Bearer <token> issued by /login (mobile app).
    Decides who/what may GET/POST to the server.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key", "").strip()
        if key and key in current_app.config.get("API_KEYS", []):
            g.api_client = {"type": "api_key"}
            return f(*args, **kwargs)

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            payload = read_token(
                auth[7:], salt="api-login",
                max_age=current_app.config["API_TOKEN_MAX_AGE"],
            )
            if payload:
                g.api_client = {"type": "bearer", "user": payload}
                return f(*args, **kwargs)

        return jsonify({
            "message": "Unauthorized: provide a valid X-API-Key header or Bearer token",
            "status": "fail",
        }), 401
    return decorated


# ---------------------------------------------------------------------------
# Signed tokens (password reset + API login) via itsdangerous
# ---------------------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_token(data, salt: str) -> str:
    return _serializer().dumps(data, salt=salt)


def read_token(token: str, salt: str, max_age: int):
    try:
        return _serializer().loads(token, salt=salt, max_age=max_age)
    except BadData:
        return None


# ---------------------------------------------------------------------------
# ECPay helper
# ---------------------------------------------------------------------------
def get_ecpay_sdk():
    """Build (once per app) an ECPay SDK from config credentials."""
    sdk = current_app.config.get("_ECPAY_SDK")
    if sdk is None:
        sdk = ecpay_payment_sdk.ECPayPaymentSdk(
            MerchantID=current_app.config["ECPAY_MERCHANT_ID"],
            HashKey=current_app.config["ECPAY_HASH_KEY"],
            HashIV=current_app.config["ECPAY_HASH_IV"],
        )
        current_app.config["_ECPAY_SDK"] = sdk
    return sdk


def create_ecpay_order(item_name=None, amount=None, custom_field="", *,
                       return_path="/payment/notify", result_path="/payment/result"):
    """
    Build + sign an ECPay order and return (signed_params, action_url).

    Reusable for ANY payment, not just VIP — pass item_name/amount per call.
    All changeable defaults (payment methods, encrypt type, default item, action
    URL) come from config, so behavior is a settings change, not a code change.
    """
    cfg = current_app.config
    base = cfg["PUBLIC_BASE_URL"].rstrip("/")
    params = {
        "MerchantTradeNo": f"DX{get_now().strftime('%Y%m%d%H%M%S')}",
        "MerchantTradeDate": get_now().strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio",
        "TotalAmount": int(amount if amount is not None else cfg["VIP_PRICE"]),
        "TradeDesc": cfg.get("ECPAY_TRADE_DESC", "Subscription"),
        "ItemName": item_name or cfg.get("ECPAY_DEFAULT_ITEM", "Item"),
        "ReturnURL": f"{base}{return_path}",
        "OrderResultURL": f"{base}{result_path}",
        "ChoosePayment": cfg.get("ECPAY_CHOOSE_PAYMENT", "ALL"),
        "EncryptType": int(cfg.get("ECPAY_ENCRYPT_TYPE", 1)),
    }
    if custom_field:
        params["CustomField1"] = custom_field
    signed = get_ecpay_sdk().create_order(params)
    return signed, cfg["ECPAY_ACTION_URL"]


# ---------------------------------------------------------------------------
# Email (optional SMTP; falls back to logging if not configured)
# ---------------------------------------------------------------------------
def send_email(to_addr: str, subject: str, body: str) -> bool:
    """Send an email if SMTP is configured; otherwise log it and return False."""
    cfg = current_app.config
    host = cfg.get("SMTP_HOST")
    if not host or not to_addr:
        logging.info(f"[EMAIL not sent — SMTP not configured] to={to_addr} :: {subject}\n{body}")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER")
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(cfg.get("SMTP_PORT", 587)), timeout=10) as s:
            if cfg.get("SMTP_USE_TLS", True):
                s.starttls()
            if cfg.get("SMTP_USER"):
                s.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception as e:
        logging.error(f"Email send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Backups (generic DB file backup) + scheduler
# ---------------------------------------------------------------------------
def create_backup(app) -> None:
    with app.app_context():
        backup_dir = app.config["BACKUP_DIR"]
        os.makedirs(backup_dir, exist_ok=True)
        ts = get_now().strftime("%Y%m%d%H%M%S")
        dest = os.path.join(backup_dir, f"backup_{ts}.db")
        src = os.path.join("instance", app.config["DATABASE_FILE"])
        if not os.path.exists(src):
            src = app.config["DATABASE_FILE"]
        try:
            if os.path.exists(src):
                shutil.copy2(src, dest)
                logging.info(f"Backup created: {dest}")
            else:
                logging.error("Source database file not found for backup!")
        except Exception as e:
            logging.error(f"Backup failed: {e}")


def delete_old_backups(app) -> None:
    with app.app_context():
        backup_dir = app.config["BACKUP_DIR"]
        if not os.path.exists(backup_dir):
            return
        cutoff = get_now() - timedelta(days=app.config["RETENTION_DAYS"])
        tz = ZoneInfo(app.config["TIMEZONE"])
        for name in os.listdir(backup_dir):
            path = os.path.join(backup_dir, name)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=tz)
                if mtime < cutoff:
                    os.remove(path)
                    logging.info(f"Deleted old backup: {path}")
            except Exception as e:
                logging.error(f"Failed to delete old backup {path}: {e}")


# ===========================================================================
# Routes (registered on a Blueprint so the app can be built via a factory)
# ===========================================================================
bp = Blueprint("main", __name__)


# ---- Account: register ----------------------------------------------------
# Optional, config-gated registration fields (address + birthday). The helpers
# below are shared by the web form and the JSON API so the rules stay identical.
_ADDRESS_FIELDS = ("country", "state", "city", "district", "zipcode", "street")


def build_address(src):
    """Pull the address fields from a form/dict into a clean dict (or None).

    `src` is request.form (web) or a dict (JSON: either a nested "address"
    object or flat keys). Returns a dict of the non-empty fields, or None if
    nothing was provided.
    """
    if isinstance(src, dict) and isinstance(src.get("address"), dict):
        src = src["address"]
    out = {}
    for key in _ADDRESS_FIELDS:
        val = (src.get(key) or "").strip() if hasattr(src, "get") else ""
        if val:
            out[key] = val
    return out or None


def address_ok(addr):
    """An address counts as provided if at least country + street are present."""
    return bool(addr and addr.get("country") and addr.get("street"))


@bp.app_context_processor
def _inject_today():
    """Expose today's date (ISO) to templates, e.g. the birthday picker's max."""
    return {"today": get_now().date().isoformat()}


def parse_birthday(value):
    """Parse a 'YYYY-MM-DD' string to a date. Returns (date|None, error|None).

    Empty input -> (None, None). Malformed or future dates -> (None, message).
    """
    value = (value or "").strip()
    if not value:
        return None, None
    try:
        bday = date.fromisoformat(value)
    except ValueError:
        return None, "生日格式不正確"
    if bday > get_now().date():
        return None, "生日不能是未來日期"
    return bday, None


@bp.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"message": "Missing username or password", "status": "fail"}), 400
    if SystemUser.query.filter_by(username=username).first():
        return jsonify({"message": "Username already exists", "status": "fail"}), 400

    role = "user"
    linked_userid = data.get("linked_userid")

    cfg = current_app.config
    address = build_address(data) if cfg["REGISTER_COLLECT_ADDRESS"] else None
    if cfg["REGISTER_COLLECT_ADDRESS"] and cfg["REGISTER_ADDRESS_REQUIRED"] and not address_ok(address):
        return jsonify({"message": "Address is required", "status": "fail"}), 400

    birthday = None
    if cfg["REGISTER_COLLECT_BIRTHDAY"]:
        birthday, bday_err = parse_birthday(data.get("birthday"))
        if bday_err or (cfg["REGISTER_BIRTHDAY_REQUIRED"] and birthday is None):
            return jsonify({"message": bday_err or "Birthday is required", "status": "fail"}), 400

    try:
        user = SystemUser(
            username=username,
            name=data.get("name"),
            email=data.get("email"),
            phone=data.get("phone"),
            linked_userid=linked_userid,
            role=role,
            address=address,
            birthday=birthday,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "User created successfully", "status": "success"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": str(e), "status": "error"}), 500


@bp.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"message": "Missing username or password"}), 400
    if SystemUser.query.filter_by(username=username).first():
        return jsonify({"message": "User already exists"}), 400
    user = SystemUser(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User created successfully"}), 201


@bp.route("/web_register", methods=["GET"])
def web_register_page():
    return render_template("register.html")


@bp.route("/web_register", methods=["POST"])
def web_register_action():
    username = request.form.get("username")
    name = request.form.get("name")
    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")
    email = request.form.get("email")
    phone = request.form.get("phone")

    role = "user"

    if not username or not password:
        return render_template("register.html", error="請填寫所有必填欄位")
    if password != confirm_password:
        return render_template("register.html", error="兩次密碼輸入不一致")
    if SystemUser.query.filter_by(username=username).first():
        return render_template("register.html", error="該帳號已被使用")

    cfg = current_app.config
    address = build_address(request.form) if cfg["REGISTER_COLLECT_ADDRESS"] else None
    if cfg["REGISTER_COLLECT_ADDRESS"] and cfg["REGISTER_ADDRESS_REQUIRED"] and not address_ok(address):
        return render_template("register.html", error="請填寫地址（至少國家與詳細地址）")

    birthday = None
    if cfg["REGISTER_COLLECT_BIRTHDAY"]:
        birthday, bday_err = parse_birthday(request.form.get("birthday"))
        if bday_err:
            return render_template("register.html", error=bday_err)
        if cfg["REGISTER_BIRTHDAY_REQUIRED"] and birthday is None:
            return render_template("register.html", error="請選擇生日")

    try:
        user = SystemUser(username=username, name=name, role=role,
                          linked_userid=None, email=email, phone=phone,
                          address=address, birthday=birthday)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return render_template("login.html", error="註冊成功！")
    except Exception as e:
        db.session.rollback()
        return render_template("register.html", error=f"註冊失敗: {e}")


# ---- Account: login / session / token -------------------------------------
@bp.route("/login", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_LOGIN"])
def api_login():
    data = request.json or {}
    user = SystemUser.query.filter_by(username=data.get("username")).first()
    if user and user.check_password(data.get("password")):
        vip_date = (user.vip_expires_at.strftime("%Y-%m-%d")
                    if user.is_vip and user.vip_expires_at else "")
        # Issue a bearer token the mobile app sends back to reach the API.
        token = make_token({"user_id": user.id, "username": user.username},
                           salt="api-login")
        return jsonify({
            "message": "Login successful", "status": "success",
            "token": token, "user_id": user.id, "username": user.username,
            "linked_userid": getattr(user, "linked_userid", ""),
            "is_vip": user.is_vip, "vip_expires_at": vip_date,
        }), 200
    return jsonify({"message": "Invalid credentials", "status": "fail"}), 401


@bp.route("/login", methods=["GET"])
def web_login_page():
    if "user_id" in session:
        return redirect(url_for("main.index"))
    return render_template("login.html")


@bp.route("/web_login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_LOGIN"])
def web_login_action():
    if request.method == "POST":
        user = SystemUser.query.filter_by(username=request.form.get("username")).first()
        if user and user.check_password(request.form.get("password")):
            session["user_id"] = user.id
            session["username"] = user.username
            session.permanent = False
            return redirect(url_for("main.personal_page"))
        return render_template("login.html", error="帳號或密碼錯誤")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.web_login_page"))


# ---- Account: password reset ----------------------------------------------
@bp.route("/forgot_password", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_RESET"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username")
        user = SystemUser.query.filter_by(username=username).first()
        # Always show the same message (don't leak which accounts exist).
        if user:
            token = make_token({"user_id": user.id}, salt="pw-reset")
            reset_url = url_for("main.reset_password", token=token, _external=True)
            # Email the link if SMTP is configured; otherwise send_email() logs it (dev hook).
            send_email(user.email, "Password reset",
                       f"Use this link to reset your password:\n{reset_url}")
            logging.info(f"[PASSWORD RESET] {username}: {reset_url}")
        return render_template("forgot_password.html",
                               message="若該帳號存在，重設連結已寄出（開發模式請看伺服器日誌）。")
    return render_template("forgot_password.html")


@bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    payload = read_token(token, salt="pw-reset",
                         max_age=current_app.config["RESET_TOKEN_MAX_AGE"])
    if not payload:
        return render_template("reset_password.html", error="連結無效或已過期。", token=None)

    if request.method == "POST":
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")
        if not password or password != confirm:
            return render_template("reset_password.html",
                                   error="兩次密碼輸入不一致。", token=token)
        user = db.session.get(SystemUser, payload["user_id"])
        if not user:
            return render_template("reset_password.html", error="找不到帳號。", token=None)
        user.set_password(password)
        db.session.commit()
        return render_template("login.html", error="密碼已重設，請重新登入。")
    return render_template("reset_password.html", token=token)


@bp.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    user = db.session.get(SystemUser, session["user_id"])
    if request.method == "POST":
        current = request.form.get("current_password")
        new = request.form.get("new_password")
        confirm = request.form.get("confirm_password")
        if not user or not user.check_password(current):
            return render_template("change_password.html", error="目前密碼不正確。")
        if not new or new != confirm:
            return render_template("change_password.html", error="兩次新密碼輸入不一致。")
        user.set_password(new)
        db.session.commit()
        return render_template("change_password.html", message="密碼已更新。")
    return render_template("change_password.html")


# ---- Account: profile update (API) ----------------------------------------
@bp.route("/api/update_profile", methods=["POST"])
def update_profile():
    data = request.json or {}
    user = SystemUser.query.filter_by(username=data.get("username")).first()
    if not user:
        return jsonify({"message": "User not found", "status": "fail"}), 404
    if "name" in data:
        user.name = data.get("name")
    if "email" in data:
        user.email = data.get("email")
    if "phone" in data:
        user.phone = data.get("phone")
    if data.get("userID"):
        user.linked_userid = data.get("userID")
    db.session.commit()
    return jsonify({"message": "Profile updated", "status": "success"}), 200


# ---- Payment + ECPay ------------------------------------------------------
@bp.route("/pay_vip")
@login_required
def pay_vip():
    user = db.session.get(SystemUser, session["user_id"])
    try:
        params, action = create_ecpay_order(
            item_name=current_app.config.get("ECPAY_DEFAULT_ITEM", "Premium_Membership"),
            amount=current_app.config["VIP_PRICE"],
            custom_field=user.username,
        )
        return render_template("ecpay_submit.html", params=params, action=action)
    except Exception as e:
        logging.error(f"ECPay order creation failed: {e}")
        return "Order Creation Failed", 500


@bp.route("/payment/notify", methods=["POST"])
@csrf.exempt
def payment_notify():
    data = request.form.to_dict()
    try:
        if data.get("CheckMacValue") == get_ecpay_sdk().generate_check_value(data):
            if data.get("RtnCode") == "1":
                user = SystemUser.query.filter_by(
                    username=data.get("CustomField1")).first()
                if user:
                    user.is_vip = True
                    user.vip_expires_at = get_now() + timedelta(
                        days=current_app.config["VIP_DAYS"])
                    db.session.add(PaymentLog(
                        username=user.username, status="SUCCESS",
                        details=f"VIP activated for {current_app.config['VIP_DAYS']} days"))
                    db.session.commit()
            return "1|OK"
        return "CheckMacValue Mismatch", 400
    except Exception as e:
        logging.error(f"Payment notify error: {e}")
        return str(e), 400


@bp.route("/payment/result", methods=["POST"])
@csrf.exempt
def payment_result():
    return render_template("payment_success.html",
                           order_id=request.form.get("MerchantTradeNo"),
                           amount=request.form.get("TradeAmt"))


# ---- VIP (admin utilities) ------------------------------------------------
@bp.route("/admin/set_vip", methods=["POST"])
@admin_required
def set_vip():
    user = SystemUser.query.filter_by(username=request.form.get("username")).first()
    if user:
        user.is_vip = True
        user.vip_expires_at = get_now() + timedelta(days=current_app.config["VIP_DAYS"])
        db.session.commit()
    return redirect(request.referrer or url_for("main.admin_accounts"))


@bp.route("/admin/reset_vip", methods=["POST"])
@admin_required
def reset_vip():
    user = SystemUser.query.filter_by(username=request.form.get("username")).first()
    if user:
        user.is_vip = False
        user.vip_expires_at = None
        db.session.commit()
    return redirect(request.referrer or url_for("main.admin_accounts"))


# ---- Account management (admin) -------------------------------------------
@bp.route("/admin/accounts")
@admin_required
def admin_accounts():
    keyword = request.args.get("q", "").strip()
    query = SystemUser.query
    if keyword:
        query = query.filter(SystemUser.username.like(f"%{keyword}%"))
    accounts = query.order_by(SystemUser.id.desc()).all()
    return render_template("admin_accounts.html", accounts=accounts,
                           sys_user=g.current_user, keyword=keyword)


@bp.route("/admin/create_account", methods=["POST"])
@admin_required
def admin_create_account():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return redirect(url_for("main.admin_accounts"))
    if SystemUser.query.filter_by(username=username).first():
        return "帳號已存在", 400
    try:
        user = SystemUser(
            username=username, email=request.form.get("email"),
            phone=request.form.get("phone"),
            linked_userid=request.form.get("linked_userid") or None, role="user")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return str(e), 500
    return redirect(url_for("main.admin_accounts"))


@bp.route("/admin/edit_account", methods=["POST"])
@admin_required
def admin_edit_account():
    user = db.session.get(SystemUser, request.form.get("account_id"))
    if user:
        new_role = request.form.get("role")
        # Only a superadmin may touch elevated accounts or grant elevated roles.
        if not can_manage(g.current_user, target=user, new_role=new_role):
            return "權限不足：僅限超級管理員", 403
        user.email = request.form.get("email")
        user.phone = request.form.get("phone")
        if new_role:
            user.role = new_role
        new_password = request.form.get("password")
        if new_password and new_password.strip():
            user.set_password(new_password)
        db.session.commit()
    return redirect(url_for("main.admin_accounts"))


@bp.route("/admin/update_binding", methods=["POST"])
@admin_required
def update_binding():
    user = db.session.get(SystemUser, request.form.get("account_id"))
    if user:
        if not can_manage(g.current_user, target=user):
            return "權限不足：僅限超級管理員", 403
        new_userid = request.form.get("linked_userid", "").strip()
        user.linked_userid = new_userid or None
        db.session.commit()
    return redirect(url_for("main.admin_accounts"))


@bp.route("/admin/delete_account", methods=["POST"])
@admin_required
def delete_account():
    target = db.session.get(SystemUser, request.form.get("account_id"))
    if target:
        if target.id == g.current_user.id:
            return "操作失敗：您無法刪除自己", 400
        if not can_manage(g.current_user, target=target):
            return "權限不足：僅限超級管理員", 403
        db.session.delete(target)
        db.session.commit()
    return redirect(url_for("main.admin_accounts"))


# ---- Per-person database sorting ------------------------------------------
@bp.route("/")
@login_required
def index():
    return redirect(url_for("main.list_users"))


@bp.route("/personal")
@login_required
def personal_page():
    user = db.session.get(SystemUser, session.get("user_id"))
    if not user:
        session.clear()
        return redirect(url_for("main.web_login_page"))

    # Auto-expire VIP.
    if user.is_vip and user.vip_expires_at:
        if get_now().replace(tzinfo=None) > user.vip_expires_at:
            user.is_vip = False
            db.session.commit()

    is_admin = user.role in ADMIN_ROLES
    records = []
    if not is_admin:
        target = user.name or user.username
        records = (UserData.query.filter_by(name=target)
                   .order_by(UserData.timestamp.desc()).all())
        for r in records:
            r.timestamp = to_local(r.timestamp)
    return render_template("personal.html", sys_user=user,
                           is_admin=is_admin, records=records)


@bp.route("/users", methods=["GET"])
@login_required
def list_users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "", type=str).strip()
    user = db.session.get(SystemUser, session.get("user_id"))
    if not user:
        session.clear()
        return redirect(url_for("main.web_login_page"))

    query = UserInfo.query
    # Permission filter: plain users see only their own records; admins see all.
    if user.role not in ADMIN_ROLES:
        target = user.name or user.username
        query = query.filter_by(name=target, phone=user.phone)

    if search:
        query = query.filter(or_(UserInfo.userID.like(f"%{search}%"),
                                 UserInfo.name.like(f"%{search}%")))
    pagination = query.order_by(UserInfo.time.desc()).paginate(page=page, per_page=50)
    return render_template("users.html", users=pagination.items, pagination=pagination,
                           current_role=user.role)


@bp.route("/user_data/<user_id>/<name>", methods=["GET"])
@login_required
def user_data(user_id, name):
    person = UserInfo.query.filter_by(userID=user_id, name=name).first()
    if not person:
        return jsonify({"message": "User not found"}), 404
    page = request.args.get("page", 1, type=int)
    pagination = (UserData.query.filter_by(userID=person.userID, name=person.name)
                  .order_by(UserData.timestamp.desc()).paginate(page=page, per_page=200))
    records = pagination.items
    for r in records:
        r.timestamp = to_local(r.timestamp)
    return render_template("user_data.html", user=person,
                           data_entries=records, pagination=pagination)


@bp.route("/delete_user/<user_id>/<name>", methods=["POST"])
@login_required
def delete_user(user_id, name):
    person = UserInfo.query.filter_by(userID=user_id, name=name).first()
    if not person:
        return jsonify({"message": "User not found"}), 404
    try:
        UserData.query.filter_by(userID=person.userID, name=person.name).delete()
        db.session.delete(person)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return str(e), 500
    return redirect(url_for("main.list_users"))


# ---- Protected external data API ------------------------------------------
@bp.route("/save", methods=["POST"])
@csrf.exempt
@api_key_required
@limiter.limit(lambda: current_app.config["RATELIMIT_SAVE"])
def save_data():
    """Receive data from an outside client. Requires X-API-Key / Bearer token."""
    try:
        body = request.get_json(force=True) or {}
        info = body.get("userInfo") or {}
        if not info.get("userID") or not info.get("name"):
            return jsonify({"message": "userInfo.userID and userInfo.name required"}), 400
        info["name"] = str(info["name"]).replace(" ", "")

        person = UserInfo.query.filter_by(userID=info["userID"], name=info["name"]).first()
        # Core generic person fields; everything else goes into meta (no schema change).
        core = {"phone": info.get("phone", ""), "device": info.get("device", ""),
                "time": info.get("time", get_now().strftime("%Y-%m-%d %H:%M:%S"))}
        extras = {k: v for k, v in info.items()
                  if k not in ("userID", "name", "phone", "device", "time")}
        if person:
            for k, v in core.items():
                setattr(person, k, v)
            if extras:
                person.meta = {**(person.meta or {}), **extras}
        else:
            person = UserInfo(userID=info["userID"], name=info["name"],
                              meta=extras or None, **core)
            db.session.add(person)

        # Generic payload: store body["data"] if present, else the whole body.
        payload = body.get("data") if "data" in body else body
        db.session.add(UserData(userID=info["userID"], name=info["name"], data=payload))
        db.session.commit()
        return jsonify({"message": "Data saved", "status": "success"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": str(e), "status": "error"}), 400


@bp.route("/log", methods=["GET"])
@api_key_required
def get_log():
    """Recent records (most recent first). Requires API auth."""
    rows = (UserData.query.order_by(UserData.timestamp.desc()).limit(100).all())
    return jsonify([
        {"userID": r.userID, "name": r.name,
         "time": to_local(r.timestamp).strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else None}
        for r in rows
    ]), 200


# ===========================================================================
# Application factory
# ===========================================================================
def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    # Behind a reverse proxy (nginx), honor X-Forwarded-Proto/For/Host so HTTPS
    # detection (Secure cookies, external URLs) and real client IPs work.
    if app.config.get("TRUST_PROXY", False):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    if app.config.get("RATELIMIT_ENABLED", True):
        limiter.init_app(app)

    # Make csrf_token() available in templates even if Flask-WTF is absent.
    if not _HAS_CSRF:
        app.jinja_env.globals.setdefault("csrf_token", lambda: "")

    app.register_blueprint(bp)
    _warn_insecure_production(app)
    return app


def _warn_insecure_production(app: Flask) -> None:
    """In production, loudly warn if shipped default secrets are still in place."""
    if os.getenv("APP_ENV", "development").lower() != "production":
        return
    if app.config.get("SECRET_KEY") == "super-secret-key-change-this-in-production":
        logging.warning("⚠️  SECRET_KEY is still the default — set a strong SECRET_KEY in .env!")
    if app.config.get("DEFAULT_ADMIN_PASSWORD") == "admin12345":
        logging.warning("⚠️  DEFAULT_ADMIN_PASSWORD is still the default — change it in .env!")


def seed_default_admin(app: Flask) -> None:
    """Create the default admin account on first run (if it doesn't exist)."""
    if not app.config.get("DEFAULT_ADMIN_ENABLED", False):
        return
    with app.app_context():
        username = app.config["DEFAULT_ADMIN_USERNAME"]
        if SystemUser.query.filter_by(username=username).first():
            return  # already exists; never overwrite
        user = SystemUser(username=username, name=username,
                          role=app.config.get("DEFAULT_ADMIN_ROLE", "superadmin"))
        user.set_password(app.config["DEFAULT_ADMIN_PASSWORD"])
        db.session.add(user)
        db.session.commit()
        logging.warning(
            f"⚠️  Seeded default admin '{username}' (role {user.role}). "
            "CHANGE ITS PASSWORD immediately, or set DEFAULT_ADMIN_* in .env."
        )


def init_runtime(app: Flask, with_scheduler: bool = True) -> None:
    """Side effects that should run only when actually serving (not on import)."""
    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
    with app.app_context():
        if os.path.isdir(migrations_dir):
            # Canonical path: apply Alembic migrations (enables easy schema evolution).
            migrate_upgrade(directory=migrations_dir)
            logging.info("✅ Database migrations applied (flask db upgrade)")
        else:
            # Fallback for a brand-new checkout with no migrations yet.
            db.create_all()
            logging.info("✅ Database tables created (db.create_all)")
    seed_default_admin(app)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "static", "data"), exist_ok=True)
    if with_scheduler:
        scheduler = BackgroundScheduler()
        tz = ZoneInfo(app.config["TIMEZONE"])
        scheduler.add_job(create_backup, CronTrigger(hour=12, minute=30, timezone=tz),
                          args=[app])
        scheduler.add_job(delete_old_backups, CronTrigger(hour=12, minute=35, timezone=tz),
                          args=[app])
        scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    init_runtime(app)
    port = app.config["PORT"]
    if (os.getenv("APP_ENV", "development").lower() == "production"):
        # Production: use waitress (works on Windows and Linux).
        from waitress import serve
        logging.info(f"Starting waitress (production) on port {port}...")
        serve(app, host="0.0.0.0", port=port, threads=8)
    else:
        from werkzeug.serving import run_simple
        logging.info(f"Starting dev server on port {port}...")
        run_simple("0.0.0.0", port, app, use_reloader=False, threaded=True)
