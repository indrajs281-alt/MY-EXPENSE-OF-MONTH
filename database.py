"""SQLAlchemy models and database helpers for the expense tracker."""

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask_login import UserMixin
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import URL, make_url


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATABASE_PATH = INSTANCE_DIR / "expenses.db"
ON_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if ON_VERCEL:
            raise RuntimeError(
                "DATABASE_URL is missing. Set it to your Supabase PostgreSQL "
                "connection string in Vercel Project Settings > Environment Variables."
            )
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        return URL.create("sqlite", database=str(DATABASE_PATH))

    url = url.replace("postgres://", "postgresql://", 1)
    if not url.startswith(("postgresql://", "postgresql+psycopg://", "sqlite://")):
        raise RuntimeError(
            "DATABASE_URL must use PostgreSQL (Supabase) or SQLite for local development."
        )
    parsed_url = make_url(url)
    if parsed_url.drivername == "postgresql":
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    if parsed_url.drivername.startswith("postgresql"):
        query = dict(parsed_url.query)
        query.setdefault("sslmode", "require")
        parsed_url = parsed_url.set(query=query)
    return parsed_url


DATABASE_URL = _database_url()
IS_SQLITE = (
    DATABASE_URL.get_backend_name() if isinstance(DATABASE_URL, URL) else DATABASE_URL.split(":", 1)[0]
) == "sqlite"
engine_options = {"pool_pre_ping": True}
if IS_SQLITE:
    engine_options["connect_args"] = {"check_same_thread": False}
else:
    engine_options["pool_recycle"] = 300
    engine_options["pool_size"] = 1
    engine_options["max_overflow"] = 0
    engine_options["connect_args"] = {"prepare_threshold": None}

engine = create_engine(DATABASE_URL, **engine_options)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class User(UserMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(254), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)


class SalaryRecord(Base):
    __tablename__ = "salary"
    __table_args__ = (
        UniqueConstraint("user_id", "month", "year", name="uq_salary_user_period"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_salary_month"),
        CheckConstraint("amount_paise >= 0", name="ck_salary_amount"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    amount_paise = Column(Integer, nullable=False)
    received = Column(Integer, nullable=False, default=0)
    notes = Column(String, nullable=False, default="")


class EMIRecord(Base):
    __tablename__ = "emi"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_emi_amount"),
        CheckConstraint("status IN ('Paid', 'Unpaid')", name="ck_emi_status"),
        Index("idx_emi_user_due_date", "user_id", "due_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    amount_paise = Column(Integer, nullable=False)
    due_date = Column(String(10), nullable=False)
    status = Column(String(10), nullable=False, default="Unpaid")
    payment_date = Column(String(10))
    notes = Column(String, nullable=False, default="")


class DailyExpense(Base):
    __tablename__ = "daily_expenses"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_expense_amount"),
        Index("idx_expenses_user_date", "user_id", "expense_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expense_date = Column(String(10), nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    amount_paise = Column(Integer, nullable=False)
    payment_method = Column(String, nullable=False)


class FuelCharge(Base):
    __tablename__ = "fuel_charges"
    __table_args__ = (
        CheckConstraint("total_cost_paise > 0", name="ck_fuel_cost"),
        Index("idx_fuel_user_date", "user_id", "fuel_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fuel_date = Column(String(10), nullable=False)
    vehicle_type = Column(String, nullable=False)
    fuel_type = Column(String, nullable=False)
    quantity_litres = Column(String)
    price_per_litre_paise = Column(Integer)
    total_cost_paise = Column(Integer, nullable=False)
    notes = Column(String, nullable=False, default="")


class ResultProxy:
    """Keep the original app's dictionary-row interface over SQLAlchemy."""

    def __init__(self, result):
        self._result = result
        self._mappings = result.mappings()

    def fetchone(self):
        return self._mappings.fetchone()

    def fetchall(self):
        return self._mappings.fetchall()

    @property
    def rowcount(self):
        return self._result.rowcount


class ConnectionProxy:
    """Allow existing parameterized SQL to run safely through SQLAlchemy."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement, parameters=()):
        if isinstance(parameters, dict):
            return ResultProxy(self._connection.execute(text(statement), parameters))

        values = tuple(parameters or ())
        position = 0

        def bind_parameter(_):
            nonlocal position
            name = f"p{position}"
            position += 1
            return f":{name}"

        converted = re.sub(r"\?", bind_parameter, statement)
        if position != len(values):
            raise ValueError("SQL parameter count does not match the query.")
        bindings = {f"p{index}": value for index, value in enumerate(values)}
        return ResultProxy(self._connection.execute(text(converted), bindings))


@contextmanager
def get_connection():
    """Open a transactional SQLAlchemy connection."""
    with engine.begin() as connection:
        yield ConnectionProxy(connection)


@contextmanager
def get_session():
    """Open an ORM session and commit or roll back as appropriate."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _add_legacy_user_columns():
    """Add nullable ownership columns to tables created by the old SQLite app."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name in ("salary", "emi", "daily_expenses", "fuel_charges"):
            if table_name not in existing_tables:
                continue
            columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
            if "user_id" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER "
                        "REFERENCES users(id) ON DELETE CASCADE"
                    )
                )


def _upgrade_sqlite_salary_constraint():
    """Replace the old global month/year uniqueness with per-user uniqueness."""
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute("PRAGMA index_list('salary')")
        indexes = cursor.fetchall()
        has_global_unique = False
        for index in indexes:
            if not index[2]:
                continue
            cursor.execute(f"PRAGMA index_info('{index[1]}')")
            columns = [row[2] for row in cursor.fetchall()]
            if columns == ["month", "year"]:
                has_global_unique = True
                break
        if not has_global_unique:
            return

        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute(
            """CREATE TABLE salary_migration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                year INTEGER NOT NULL,
                amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
                received INTEGER NOT NULL DEFAULT 0 CHECK (received IN (0, 1)),
                notes TEXT NOT NULL DEFAULT '',
                CONSTRAINT uq_salary_user_period UNIQUE (user_id, month, year)
            )"""
        )
        cursor.execute(
            """INSERT INTO salary_migration
               (id, user_id, month, year, amount_paise, received, notes)
               SELECT id, user_id, month, year, amount_paise, received, notes FROM salary"""
        )
        cursor.execute("DROP TABLE salary")
        cursor.execute("ALTER TABLE salary_migration RENAME TO salary")
        raw_connection.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def _upgrade_postgres_salary_constraint():
    """Remove a legacy global salary constraint and install the account-scoped one."""
    inspector = inspect(engine)
    constraints = inspector.get_unique_constraints("salary")
    with engine.begin() as connection:
        for constraint in constraints:
            if set(constraint.get("column_names") or []) == {"month", "year"}:
                name = constraint["name"].replace('"', '""')
                connection.execute(text(f'ALTER TABLE salary DROP CONSTRAINT "{name}"'))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_salary_user_period "
                "ON salary (user_id, month, year)"
            )
        )


def initialize_db():
    """Create missing tables and safely add account ownership to legacy tables."""
    Base.metadata.create_all(engine)
    _add_legacy_user_columns()
    if IS_SQLITE:
        _upgrade_sqlite_salary_constraint()
    else:
        _upgrade_postgres_salary_constraint()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_emi_user_due_date "
                "ON emi (user_id, due_date)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_expenses_user_date "
                "ON daily_expenses (user_id, expense_date)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_fuel_user_date "
                "ON fuel_charges (user_id, fuel_date)"
            )
        )


def migrate_sqlite_records(email):
    """Copy the local SQLite financial records to this user's configured database."""
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"No local SQLite database found at {DATABASE_PATH}.")
    if IS_SQLITE:
        raise RuntimeError(
            "DATABASE_URL currently points to SQLite. Set DATABASE_URL to Supabase "
            "PostgreSQL before running the migration command."
        )

    with get_session() as session:
        user = session.query(User).filter_by(email=email.strip().lower()).one_or_none()
        if user is None:
            raise ValueError("Register this email in the PostgreSQL app before migrating.")
        user_id = user.id

    tables = ("salary", "emi", "daily_expenses", "fuel_charges")
    copied = {}
    source = sqlite3.connect(DATABASE_PATH)
    source.row_factory = sqlite3.Row
    try:
        with engine.begin() as target:
            for table_name in tables:
                source_columns = {
                    row[1] for row in source.execute(f"PRAGMA table_info({table_name})")
                }
                if not source_columns:
                    copied[table_name] = 0
                    continue
                column_names = sorted(source_columns - {"user_id"})
                rows = source.execute(
                    f"SELECT {', '.join(column_names)} FROM {table_name}"
                ).fetchall()
                count = 0
                for row in rows:
                    values = dict(row)
                    if table_name == "salary":
                        existing_period = target.execute(
                            text(
                                "SELECT id FROM salary WHERE user_id = :user_id "
                                "AND month = :month AND year = :year"
                            ),
                            {
                                "user_id": user_id,
                                "month": values["month"],
                                "year": values["year"],
                            },
                        ).first()
                        if existing_period:
                            continue
                    existing = target.execute(
                        text(f"SELECT id FROM {table_name} WHERE id = :id"),
                        {"id": values["id"]},
                    ).first()
                    if existing:
                        continue
                    values["user_id"] = user_id
                    insert_columns = list(values)
                    placeholders = ", ".join(f":{name}" for name in insert_columns)
                    target.execute(
                        text(
                            f"INSERT INTO {table_name} "
                            f"({', '.join(insert_columns)}) VALUES ({placeholders})"
                        ),
                        values,
                    )
                    count += 1
                copied[table_name] = count
            if engine.dialect.name == "postgresql":
                for table_name in tables:
                    target.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table_name}"
                        ),
                        {"table_name": table_name},
                    )
    finally:
        source.close()
    return copied
