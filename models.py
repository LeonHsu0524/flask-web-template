from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import PrimaryKeyConstraint, ForeignKeyConstraint
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# -----------------------
# Models
# -----------------------
class SystemUser(db.Model):
    __bind_key__ = "user_db"
    __tablename__ = "system_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(db.String(80), unique=True)
    name: Mapped[str | None] = mapped_column(db.String(120))
    password_hash: Mapped[str] = mapped_column(db.String(255))
    # role: 'user' | 'admin' | 'superadmin'
    role: Mapped[str] = mapped_column(db.String(20), default='user')
    is_vip: Mapped[bool] = mapped_column(default=False)
    email: Mapped[str | None] = mapped_column(db.String(120))
    phone: Mapped[str | None] = mapped_column(db.String(20))
    height: Mapped[str | None] = mapped_column(db.String(20))
    weight: Mapped[str | None] = mapped_column(db.String(20))
    age: Mapped[str | None] = mapped_column(db.String(10))
    vip_expires_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    linked_userid: Mapped[str | None] = mapped_column(db.String(50))

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class PaymentLog(db.Model):
    __bind_key__ = "user_db"
    __tablename__ = "payment_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(db.String(80))
    timestamp: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str]= mapped_column(db.String(50)) # 例如：'SUCCESS', 'DISABLED_DATE', 'EXPIRED'
    details: Mapped[str] = mapped_column(db.Text)

class UserInfo(db.Model):
    __tablename__ = "user_info"
    userID: Mapped[str] = mapped_column(db.String(80))
    name: Mapped[str] = mapped_column(db.String(120))
    sex: Mapped[int] = mapped_column()
    age: Mapped[int] = mapped_column()
    height: Mapped[int] = mapped_column()
    weight: Mapped[int] = mapped_column()
    phone: Mapped[str] = mapped_column(db.String(20))
    device: Mapped[str] = mapped_column(db.String(120))
    time: Mapped[str] = mapped_column(db.String(120))
    __table_args__ = (PrimaryKeyConstraint("userID", "name"),)

class UserData(db.Model):
    __tablename__ = "user_data"
    id: Mapped[int] = mapped_column(primary_key=True)
    userID: Mapped[str] = mapped_column(db.String(80))
    name: Mapped[str] = mapped_column(db.String(120))
    # Generic JSON payload. The external API (/save) stores whatever shape the
    # client sends here, so this template is not tied to any one data domain.
    # In Python, JSON values are dicts or lists.
    data: Mapped[dict] = mapped_column(db.JSON)
    timestamp: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    __table_args__ = (
        ForeignKeyConstraint(["userID", "name"], ["user_info.userID", "user_info.name"]),
    )