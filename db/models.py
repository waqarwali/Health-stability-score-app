from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship


class Base(DeclarativeBase):
    """The base class used by SQLAlchemy for its registry mapping."""


class User(Base):
    """Reflects application users."""

    __tablename__ = "users"

    user_id         = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(Text,    nullable=False)
    email           = Column(Text,    nullable=False, unique=True)
    timezone        = Column(Text,    nullable=False, default="UTC")
    target_sleep_hr = Column(Float,   nullable=False, default=8.0)
    target_water_ml = Column(Integer, nullable=False, default=2500)
    target_steps    = Column(Integer, nullable=False, default=8000)
    created_at      = Column(DateTime, default=datetime.utcnow)

    logs         = relationship("DailyLog",       back_populates="user", cascade="all, delete-orphan")
    habit_scores = relationship("HabitScore",     back_populates="user", cascade="all, delete-orphan")
    scores       = relationship("StabilityScore", back_populates="user", cascade="all, delete-orphan")
    disruptions  = relationship("Disruption",     back_populates="user", cascade="all, delete-orphan")
    suggestions  = relationship("Suggestion",     back_populates="user", cascade="all, delete-orphan")


class DailyLog(Base):
    """Saves daily habits"""

    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_daily_logs_user_date"),
    )

    log_id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id            = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    log_date           = Column(Date,    nullable=False)
    sleep_start        = Column(String)
    sleep_end          = Column(String)
    wake_time          = Column(String)
    sleep_duration_hr  = Column(Float)
    meal_times         = Column(Text)
    steps              = Column(Integer, nullable=False, default=0)
    water_ml           = Column(Integer, nullable=False, default=0)
    screen_min         = Column(Integer, nullable=False, default=0)
    mood_score         = Column(Integer, CheckConstraint("mood_score BETWEEN 1 AND 10"))
    energy_score       = Column(Integer, CheckConstraint("energy_score BETWEEN 1 AND 10"))
    productivity_score = Column(Integer, CheckConstraint("productivity_score BETWEEN 1 AND 10"))
    notes              = Column(Text)
    created_at         = Column(DateTime, default=datetime.utcnow)

    user         = relationship("User",       back_populates="logs")
    habit_scores = relationship("HabitScore", back_populates="log", cascade="all, delete-orphan")
    disruptions  = relationship("Disruption", back_populates="log", cascade="all, delete-orphan")


class HabitScore(Base):
    """A scored breakdown calculated for each custom habit."""

    __tablename__ = "habit_scores"

    score_id       = Column(Integer, primary_key=True, autoincrement=True)
    log_id         = Column(Integer, ForeignKey("daily_logs.log_id", ondelete="CASCADE"), nullable=False)
    user_id        = Column(Integer, ForeignKey("users.user_id",     ondelete="CASCADE"), nullable=False)
    habit_type     = Column(Text,    nullable=False)
    raw_value      = Column(Float)
    seven_day_mean = Column(Float)
    seven_day_std  = Column(Float)
    deviation      = Column(Float)
    stability_pct  = Column(Float, CheckConstraint("stability_pct BETWEEN 0 AND 100"))
    is_disrupted   = Column(Integer, nullable=False, default=0)
    computed_at    = Column(DateTime, default=datetime.utcnow)

    log  = relationship("DailyLog", back_populates="habit_scores")
    user = relationship("User",     back_populates="habit_scores")


class StabilityScore(Base):
    """Stores compiled values either parsed over a day or an entire week."""

    __tablename__ = "stability_scores"
    __table_args__ = (
        CheckConstraint("period_type IN ('daily','weekly')", name="ck_period_type"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    score_date      = Column(Date,   nullable=False)
    period_type     = Column(Text,   nullable=False)
    overall_score   = Column(Float)
    sleep_score     = Column(Float)
    meal_score      = Column(Float)
    activity_score  = Column(Float)
    hydration_score = Column(Float)
    screen_score    = Column(Float)
    created_at      = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="scores")


class Disruption(Base):
    """Automatically spawned when a habit drops far below standard tolerance thresholds."""

    __tablename__ = "disruptions"
    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high')", name="ck_severity"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    log_id      = Column(Integer, ForeignKey("daily_logs.log_id", ondelete="CASCADE"), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.user_id",     ondelete="CASCADE"), nullable=False)
    habit_type  = Column(Text, nullable=False)
    severity    = Column(Text, nullable=False)
    description = Column(Text)
    detected_at = Column(DateTime, default=datetime.utcnow)

    log  = relationship("DailyLog", back_populates="disruptions")
    user = relationship("User",     back_populates="disruptions")


class Suggestion(Base):
    """Tied closely with the pattern detector to warn against tracked disruptions."""

    __tablename__ = "suggestions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    week_of         = Column(Date)
    habit_type      = Column(Text)
    suggestion_text = Column(Text)
    priority        = Column(Integer, nullable=False, default=1)
    is_shown        = Column(Integer, nullable=False, default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="suggestions")


def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    """Activates foreign key cascade functionality in sqlite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()

def create_tables(engine) -> None:
    """Uses engine class instance to safely initialize missing tables on boot."""
    Base.metadata.create_all(engine)

def get_session(db_url: str) -> Session:
    """Configures sqlite correctly alongside Base bindings."""
    engine = create_engine(db_url, echo=False)
    event.listen(engine, "connect", _set_sqlite_pragma)
    create_tables(engine)
    return Session(engine)

def init_db(db_path: str = "routine.db") -> Session:
    """Simple wrapper to hook straight into root path db files easily."""
    db_url = f"sqlite:///{db_path}"
    return get_session(db_url)
