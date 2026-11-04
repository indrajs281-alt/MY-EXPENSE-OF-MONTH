"""A beginner-friendly multi-user expense tracker for Flask and Supabase."""

import calendar
import os
import re
import secrets
from threading import Lock
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import click
from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    BASE_DIR,
    ON_VERCEL,
    User,
    engine,
    get_connection,
    get_session,
    initialize_db,
    migrate_sqlite_records,
)

STATIC_DIR = "public/static" if (BASE_DIR / "public" / "static").is_dir() else "static"

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static",
)
secret_key = os.environ.get("SECRET_KEY")
if ON_VERCEL and not secret_key:
    raise RuntimeError(
        "SECRET_KEY is missing. Set a long random secret in Vercel Project Settings "
        "> Environment Variables."
    )
app.config.update(
    SECRET_KEY=secret_key or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=ON_VERCEL,
)
CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to view your financial records."
_database_initialized = False
_database_initialization_lock = Lock()


@app.before_request
def ensure_database_initialized():
    global _database_initialized
    if not _database_initialized:
        with _database_initialization_lock:
            if not _database_initialized:
                initialize_db()
                _database_initialized = True

    # Direct access: auto-login default account so no sign-in page is required
    if not current_user.is_authenticated:
        with get_session() as session:
            user = session.execute(
                select(User).order_by(User.id.asc())
            ).scalars().first()
            if not user:
                user = User(
                    email="personal@finance.local",
                    password_hash=generate_password_hash("password123"),
                )
                session.add(user)
                session.flush()
            login_user(user, remember=True)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if current_user.is_authenticated:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@login_manager.user_loader
def load_user(user_id):
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None
    with get_session() as session:
        return session.get(User, numeric_id)


@app.context_processor
def inject_globals():
    return {
        "today_label": date.today().strftime("%A, %d %B %Y"),
        "today_iso": date.today().isoformat(),
        "current_year": date.today().year,
    }


@app.cli.command("migrate-sqlite")
@click.option("--email", required=True, help="Registered account to own the imported records.")
def migrate_sqlite_command(email):
    """Copy records from the local SQLite database into DATABASE_URL."""
    try:
        initialize_db()
        counts = migrate_sqlite_records(email)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo("Imported rows: " + ", ".join(f"{table}={count}" for table, count in counts.items()))


@app.cli.command("claim-unassigned-records")
@click.option("--email", required=True, help="Registered account to own the records.")
def claim_unassigned_records_command(email):
    """Assign pre-authentication PostgreSQL records to a registered account."""
    initialize_db()
    with get_session() as session:
        user = session.execute(
            select(User).where(User.email == email.strip().lower())
        ).scalar_one_or_none()
        if user is None:
            raise click.ClickException("Register this email before claiming records.")
        user_id = user.id
    totals = {}
    with get_connection() as connection:
        for table_name in ("salary", "emi", "daily_expenses", "fuel_charges"):
            result = connection.execute(
                f"UPDATE {table_name} SET user_id = ? WHERE user_id IS NULL",
                (user_id,),
            )
            totals[table_name] = result.rowcount
    click.echo("Assigned rows: " + ", ".join(f"{table}={count}" for table, count in totals.items()))


@app.cli.command("check-db")
def check_database_command():
    """Verify that the configured database accepts a query."""
    initialize_db()
    with get_connection() as connection:
        connection.execute("SELECT 1").fetchone()
    click.echo(f"Database connection OK ({engine.dialect.name}).")


CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Rent",
    "Bills",
    "Medical",
    "Entertainment",
    "Other",
]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Other"]
FUEL_TYPES = ["Petrol", "Diesel", "CNG", "Other"]
VEHICLE_TYPES = ["Car", "Bike", "Scooter", "Other"]


class FormError(ValueError):
    """An error that can be shown to the user as a form message."""


def amount_to_paise(value, field_name="Amount", allow_zero=False):
    """Convert a rupee input into integer paise without float rounding."""
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite():
            raise InvalidOperation
        paise = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise FormError(f"{field_name} must be a valid amount.")
    if paise < 0 or (paise == 0 and not allow_zero):
        raise FormError(f"{field_name} must be greater than zero.")
    return int(paise)


def optional_decimal(value, field_name):
    if not value or not str(value).strip():
        return None
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number <= 0:
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        raise FormError(f"{field_name} must be a number greater than zero.")


def validate_date(value, field_name):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        raise FormError(f"Please enter a valid {field_name.lower()}.")


def selected_period(source=None):
    source = source or request.args
    today = date.today()
    try:
        month_value = str(source.get("month", today.month))
        if "-" in month_value:
            year_text, month_text = month_value.split("-", 1)
            month = int(month_text)
            year = int(source.get("year", year_text))
        else:
            month = int(month_value)
            year = int(source.get("year", today.year))
        if month < 1 or month > 12 or year < 1900 or year > 9999:
            raise ValueError
    except (TypeError, ValueError):
        month, year = today.month, today.year
        flash("That month or year was not valid. Showing the current month.", "error")
    return month, year


def month_context(month, year):
    today = date.today()
    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year

    if month == 12:
        next_month, next_year = 1, year + 1
    else:
        next_month, next_year = month + 1, year

    return {
        "month": month,
        "year": year,
        "month_name": calendar.month_name[month],
        "month_value": f"{year:04d}-{month:02d}",
        "prev_month_value": f"{prev_year:04d}-{prev_month:02d}",
        "next_month_value": f"{next_year:04d}-{next_month:02d}",
        "is_current_month": (month == today.month and year == today.year),
        "today_iso": today.isoformat(),
    }


def get_salary(month, year):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM salary WHERE user_id = ? AND month = ? AND year = ?",
            (current_user.id, month, year),
        ).fetchone()


def monthly_totals(month, year):
    month_prefix = f"{year:04d}-{month:02d}"
    today = date.today()
    with get_connection() as connection:
        salary_row = connection.execute(
            "SELECT amount_paise FROM salary WHERE user_id = ? AND month = ? AND year = ?",
            (current_user.id, month, year),
        ).fetchone()
        emi_row = connection.execute(
            """SELECT COALESCE(SUM(amount_paise), 0) AS total
               FROM emi WHERE user_id = ? AND status = 'Paid'
               AND substr(due_date, 1, 7) = ?""",
            (current_user.id, month_prefix),
        ).fetchone()
        unpaid_emi_row = connection.execute(
            """SELECT COALESCE(SUM(amount_paise), 0) AS total
               FROM emi WHERE user_id = ? AND status = 'Unpaid'
               AND substr(due_date, 1, 7) = ?""",
            (current_user.id, month_prefix),
        ).fetchone()
        expense_row = connection.execute(
            """SELECT COALESCE(SUM(amount_paise), 0) AS total
               FROM daily_expenses WHERE user_id = ?
               AND substr(expense_date, 1, 7) = ?""",
            (current_user.id, month_prefix),
        ).fetchone()
        fuel_row = connection.execute(
            """SELECT COALESCE(SUM(total_cost_paise), 0) AS total
               FROM fuel_charges WHERE user_id = ?
               AND substr(fuel_date, 1, 7) = ?""",
            (current_user.id, month_prefix),
        ).fetchone()

    salary = salary_row["amount_paise"] if salary_row else 0
    emi = emi_row["total"]
    unpaid_emi = unpaid_emi_row["total"]
    expenses = expense_row["total"]
    fuel = fuel_row["total"]
    total_expenses = emi + expenses + fuel
    balance = salary - total_expenses

    spent_percentage = min(100, int(round((total_expenses * 100) / salary))) if salary > 0 else (100 if total_expenses > 0 else 0)
    days_in_month = calendar.monthrange(year, month)[1]
    if year == today.year and month == today.month:
        days_elapsed = max(1, min(today.day, days_in_month))
        days_remaining = max(0, days_in_month - today.day)
    elif (year < today.year) or (year == today.year and month < today.month):
        days_elapsed = days_in_month
        days_remaining = 0
    else:
        days_elapsed = 0
        days_remaining = days_in_month

    daily_avg_paise = int(round(total_expenses / days_elapsed)) if days_elapsed > 0 else 0

    return {
        "salary": salary,
        "salary_entered": salary_row is not None,
        "emi": emi,
        "unpaid_emi": unpaid_emi,
        "daily_expenses": expenses,
        "fuel": fuel,
        "total_expenses": total_expenses,
        "balance": balance,
        "spent_percentage": spent_percentage,
        "daily_avg_paise": daily_avg_paise,
        "days_in_month": days_in_month,
        "days_remaining": days_remaining,
    }


def fetch_record(table, record_id):
    allowed_tables = {"emi", "daily_expenses", "fuel_charges"}
    if table not in allowed_tables:
        raise ValueError("Invalid table name.")
    with get_connection() as connection:
        record = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        ).fetchone()
    if record is None:
        abort(404)
    return record


def render_emi_page(month, year, record=None, form_data=None):
    month_prefix = f"{year:04d}-{month:02d}"
    with get_connection() as connection:
        records = connection.execute(
            """SELECT * FROM emi WHERE user_id = ? AND substr(due_date, 1, 7) = ?
               ORDER BY due_date, id""",
            (current_user.id, month_prefix),
        ).fetchall()
    paid_total = sum(row["amount_paise"] for row in records if row["status"] == "Paid")
    unpaid_total = sum(row["amount_paise"] for row in records if row["status"] == "Unpaid")
    upcoming = [row for row in records if row["status"] == "Unpaid"]
    return render_template(
        "emi.html",
        **month_context(month, year),
        records=records,
        paid_total=paid_total,
        unpaid_total=unpaid_total,
        upcoming=upcoming,
        record=record,
        form_data=form_data,
    )


def render_expenses_page(month, year, form_data=None, record=None):
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    category = request.args.get("category", "")
    search = request.args.get("q", "").strip()
    filters = [
        ("user_id = ?", current_user.id),
        ("substr(expense_date, 1, 7) = ?", f"{year:04d}-{month:02d}"),
    ]
    if start_date:
        try:
            filters.append(("expense_date >= ?", validate_date(start_date, "Start date")))
        except FormError as error:
            flash(str(error), "error")
            start_date = ""
    if end_date:
        try:
            filters.append(("expense_date <= ?", validate_date(end_date, "End date")))
        except FormError as error:
            flash(str(error), "error")
            end_date = ""
    if category in CATEGORIES:
        filters.append(("category = ?", category))
    if search:
        filters.append(("description LIKE ?", f"%{search}%"))

    where_clause = " AND ".join(item[0] for item in filters)
    parameters = tuple(item[1] for item in filters)
    with get_connection() as connection:
        records = connection.execute(
            f"SELECT * FROM daily_expenses WHERE {where_clause} ORDER BY expense_date DESC, id DESC",
            parameters,
        ).fetchall()
    total = sum(row["amount_paise"] for row in records)
    return render_template(
        "expenses.html",
        **month_context(month, year),
        records=records,
        filtered_total=total,
        categories=CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        start_date=start_date,
        end_date=end_date,
        selected_category=category,
        search_query=search,
        record=record,
        form_data=form_data,
    )


def render_fuel_page(month, year, record=None, form_data=None):
    month_prefix = f"{year:04d}-{month:02d}"
    with get_connection() as connection:
        records = connection.execute(
            """SELECT * FROM fuel_charges WHERE user_id = ?
               AND substr(fuel_date, 1, 7) = ?
               ORDER BY fuel_date DESC, id DESC""",
            (current_user.id, month_prefix),
        ).fetchall()
    total = sum(row["total_cost_paise"] for row in records)
    total_litres = sum(
        Decimal(row["quantity_litres"]) for row in records if row["quantity_litres"]
    )
    return render_template(
        "fuel.html",
        **month_context(month, year),
        records=records,
        monthly_total=total,
        total_litres=float(total_litres) if total_litres else 0.0,
        vehicle_types=VEHICLE_TYPES,
        fuel_types=FUEL_TYPES,
        record=record,
        form_data=form_data,
    )


@app.template_filter("rupees")
def rupees(paise):
    amount = Decimal(paise or 0) / Decimal(100)
    return f"₹{amount:,.2f}"


@app.template_filter("rupee_val")
def rupee_val(paise):
    """Outputs a clean float string for form input values."""
    if paise is None or paise == "":
        return ""
    try:
        amount = Decimal(paise) / Decimal(100)
        return f"{amount:.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return ""


@app.template_filter("date_display")
def date_display(value):
    if not value:
        return "—"
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return value


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    month, year = selected_period()
    totals = monthly_totals(month, year)
    month_prefix = f"{year:04d}-{month:02d}"
    today = date.today()

    with get_connection() as connection:
        upcoming_rows = connection.execute(
            """SELECT * FROM emi WHERE user_id = ? AND status = 'Unpaid'
               AND substr(due_date, 1, 7) = ? ORDER BY due_date LIMIT 6""",
            (current_user.id, month_prefix),
        ).fetchall()

        recent_daily = connection.execute(
            """SELECT 'Daily' AS kind, expense_date AS date, category, description,
                      amount_paise, payment_method, id
               FROM daily_expenses WHERE user_id = ? AND substr(expense_date, 1, 7) = ?
               ORDER BY expense_date DESC, id DESC LIMIT 5""",
            (current_user.id, month_prefix),
        ).fetchall()
        recent_fuel = connection.execute(
            """SELECT 'Fuel' AS kind, fuel_date AS date, 'Fuel' AS category,
                      vehicle_type || ' · ' || fuel_type AS description,
                      total_cost_paise AS amount_paise, 'Fuel' AS payment_method, id
               FROM fuel_charges WHERE user_id = ? AND substr(fuel_date, 1, 7) = ?
               ORDER BY fuel_date DESC, id DESC LIMIT 5""",
            (current_user.id, month_prefix),
        ).fetchall()

    upcoming = []
    for row in upcoming_rows:
        row_dict = dict(row)
        try:
            due_d = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
            diff = (due_d - today).days
            row_dict["days_left"] = diff
            row_dict["is_overdue"] = diff < 0
            row_dict["is_due_soon"] = 0 <= diff <= 5
        except (ValueError, TypeError):
            row_dict["days_left"] = None
            row_dict["is_overdue"] = False
            row_dict["is_due_soon"] = False
        upcoming.append(row_dict)

    recent_activity = sorted(
        list(recent_daily) + list(recent_fuel),
        key=lambda item: (item["date"], item["id"]),
        reverse=True,
    )[:5]

    return render_template(
        "dashboard.html",
        **month_context(month, year),
        totals=totals,
        salary=get_salary(month, year),
        upcoming=upcoming,
        recent_activity=recent_activity,
    )


@app.route("/salary", methods=["GET", "POST"])
@login_required
def salary():
    month, year = selected_period(request.form if request.method == "POST" else None)
    if request.method == "POST":
        try:
            amount = amount_to_paise(request.form.get("amount", ""), "Monthly salary", True)
            received = request.form.get("received") == "yes"
            notes = request.form.get("notes", "").strip()
            with get_connection() as connection:
                connection.execute(
                    """INSERT INTO salary (user_id, month, year, amount_paise, received, notes)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id, month, year) DO UPDATE SET
                           amount_paise = excluded.amount_paise,
                           received = excluded.received,
                           notes = excluded.notes""",
                    (current_user.id, month, year, amount, int(received), notes),
                )
            flash(f"Salary for {calendar.month_name[month]} {year} saved successfully.", "success")
            return redirect(url_for("salary", month=month, year=year))
        except FormError as error:
            flash(str(error), "error")

    current = get_salary(month, year)
    with get_connection() as connection:
        records = connection.execute(
            "SELECT * FROM salary WHERE user_id = ? ORDER BY year DESC, month DESC",
            (current_user.id,),
        ).fetchall()
    return render_template(
        "salary.html",
        **month_context(month, year),
        current=current,
        records=records,
        form_data=request.form if request.method == "POST" else None,
    )


@app.post("/salary/<int:record_id>/delete")
@login_required
def delete_salary(record_id):
    month = request.form.get("month") or request.args.get("month")
    year = request.form.get("year") or request.args.get("year")
    with get_connection() as connection:
        result = connection.execute(
            "DELETE FROM salary WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        )
    if result.rowcount == 0:
        abort(404)
    flash("Salary record deleted.", "success")
    if month and year:
        return redirect(url_for("salary", month=month, year=year))
    return redirect(url_for("salary"))


@app.route("/emi", methods=["GET", "POST"])
@login_required
def emi():
    month, year = selected_period(request.form if request.method == "POST" else None)
    record_id = request.form.get("id") if request.method == "POST" else request.args.get("edit")
    record = fetch_record("emi", int(record_id)) if record_id and record_id.isdigit() else None
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name:
                raise FormError("EMI name is required.")
            amount = amount_to_paise(request.form.get("amount", ""), "EMI amount")
            due_date = validate_date(request.form.get("due_date"), "Due date")
            status = request.form.get("status", "Unpaid")
            if status not in ("Paid", "Unpaid"):
                raise FormError("Choose Paid or Unpaid for the EMI status.")
            payment_date = request.form.get("payment_date", "").strip() or None
            if payment_date:
                payment_date = validate_date(payment_date, "Payment date")
            notes = request.form.get("notes", "").strip()
            with get_connection() as connection:
                if record_id:
                    connection.execute(
                        """UPDATE emi SET name=?, amount_paise=?, due_date=?, status=?,
                           payment_date=?, notes=? WHERE id=? AND user_id=?""",
                        (
                            name,
                            amount,
                            due_date,
                            status,
                            payment_date,
                            notes,
                            int(record_id),
                            current_user.id,
                        ),
                    )
                else:
                    connection.execute(
                        """INSERT INTO emi
                           (user_id, name, amount_paise, due_date, status, payment_date, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            current_user.id,
                            name,
                            amount,
                            due_date,
                            status,
                            payment_date,
                            notes,
                        ),
                    )
            flash("EMI record saved successfully.", "success")
            return redirect(url_for("emi", month=month, year=year))
        except FormError as error:
            flash(str(error), "error")
    return render_emi_page(month, year, record, request.form if request.method == "POST" else None)


@app.post("/emi/<int:record_id>/toggle-status")
@login_required
def toggle_emi_status(record_id):
    month = request.form.get("month") or request.args.get("month")
    year = request.form.get("year") or request.args.get("year")
    with get_connection() as connection:
        record = connection.execute(
            "SELECT status FROM emi WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        ).fetchone()
        if not record:
            abort(404)
        new_status = "Unpaid" if record["status"] == "Paid" else "Paid"
        payment_date = date.today().isoformat() if new_status == "Paid" else None
        connection.execute(
            "UPDATE emi SET status = ?, payment_date = ? WHERE id = ? AND user_id = ?",
            (new_status, payment_date, record_id, current_user.id),
        )
    flash(f"EMI status updated to {new_status}.", "success")
    if month and year:
        return redirect(url_for("emi", month=month, year=year))
    return redirect(url_for("emi"))


@app.post("/emi/<int:record_id>/delete")
@login_required
def delete_emi(record_id):
    month = request.form.get("month") or request.args.get("month")
    year = request.form.get("year") or request.args.get("year")
    with get_connection() as connection:
        result = connection.execute(
            "DELETE FROM emi WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        )
    if result.rowcount == 0:
        abort(404)
    flash("EMI record deleted.", "success")
    if month and year:
        return redirect(url_for("emi", month=month, year=year))
    return redirect(url_for("emi"))


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    month, year = selected_period(request.form if request.method == "POST" else None)
    record_id = request.form.get("id") if request.method == "POST" else request.args.get("edit")
    record = (
        fetch_record("daily_expenses", int(record_id))
        if record_id and record_id.isdigit()
        else None
    )
    if request.method == "POST":
        try:
            expense_date = validate_date(request.form.get("expense_date"), "Expense date")
            category = request.form.get("category", "")
            if category not in CATEGORIES:
                raise FormError("Choose a valid expense category.")
            description = request.form.get("description", "").strip()
            if not description:
                raise FormError("Expense description is required.")
            amount = amount_to_paise(request.form.get("amount", ""), "Expense amount")
            payment_method = request.form.get("payment_method", "")
            if payment_method not in PAYMENT_METHODS:
                raise FormError("Choose a valid payment method.")
            with get_connection() as connection:
                if record_id:
                    connection.execute(
                        """UPDATE daily_expenses SET expense_date=?, category=?, description=?,
                           amount_paise=?, payment_method=? WHERE id=? AND user_id=?""",
                        (
                            expense_date,
                            category,
                            description,
                            amount,
                            payment_method,
                            int(record_id),
                            current_user.id,
                        ),
                    )
                else:
                    connection.execute(
                        """INSERT INTO daily_expenses
                           (user_id, expense_date, category, description, amount_paise, payment_method)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            current_user.id,
                            expense_date,
                            category,
                            description,
                            amount,
                            payment_method,
                        ),
                    )
            flash("Daily expense saved successfully.", "success")
            return redirect(url_for("expenses", month=month, year=year))
        except FormError as error:
            flash(str(error), "error")
    return render_expenses_page(
        month, year, request.form if request.method == "POST" else None, record
    )


@app.post("/expenses/<int:record_id>/delete")
@login_required
def delete_expense(record_id):
    month = request.form.get("month") or request.args.get("month")
    year = request.form.get("year") or request.args.get("year")
    with get_connection() as connection:
        result = connection.execute(
            "DELETE FROM daily_expenses WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        )
    if result.rowcount == 0:
        abort(404)
    flash("Daily expense deleted.", "success")
    if month and year:
        return redirect(url_for("expenses", month=month, year=year))
    return redirect(url_for("expenses"))


@app.route("/fuel", methods=["GET", "POST"])
@login_required
def fuel():
    month, year = selected_period(request.form if request.method == "POST" else None)
    record_id = request.form.get("id") if request.method == "POST" else request.args.get("edit")
    record = (
        fetch_record("fuel_charges", int(record_id))
        if record_id and record_id.isdigit()
        else None
    )
    if request.method == "POST":
        try:
            fuel_date = validate_date(request.form.get("fuel_date"), "Fuel date")
            vehicle_type = request.form.get("vehicle_type", "")
            fuel_type = request.form.get("fuel_type", "")
            if vehicle_type not in VEHICLE_TYPES or fuel_type not in FUEL_TYPES:
                raise FormError("Choose a valid vehicle type and fuel type.")
            quantity = optional_decimal(request.form.get("quantity_litres", ""), "Quantity")
            price_text = request.form.get("price_per_litre", "").strip()
            price_paise = (
                amount_to_paise(price_text, "Price per litre") if price_text else None
            )
            total_text = request.form.get("total_cost", "").strip()
            if quantity is not None and price_paise is not None:
                total_paise = int(
                    (quantity * Decimal(price_paise)).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
            elif total_text:
                total_paise = amount_to_paise(total_text, "Total fuel cost")
            else:
                raise FormError(
                    "Enter quantity and price per litre, or enter the total fuel cost."
                )
            if total_paise <= 0:
                raise FormError("Total fuel cost must be greater than zero.")
            notes = request.form.get("notes", "").strip()
            with get_connection() as connection:
                if record_id:
                    connection.execute(
                        """UPDATE fuel_charges SET fuel_date=?, vehicle_type=?, fuel_type=?,
                           quantity_litres=?, price_per_litre_paise=?, total_cost_paise=?, notes=?
                           WHERE id=? AND user_id=?""",
                        (
                            fuel_date,
                            vehicle_type,
                            fuel_type,
                            str(quantity) if quantity is not None else None,
                            price_paise,
                            total_paise,
                            notes,
                            int(record_id),
                            current_user.id,
                        ),
                    )
                else:
                    connection.execute(
                        """INSERT INTO fuel_charges
                           (user_id, fuel_date, vehicle_type, fuel_type, quantity_litres,
                            price_per_litre_paise, total_cost_paise, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            current_user.id,
                            fuel_date,
                            vehicle_type,
                            fuel_type,
                            str(quantity) if quantity is not None else None,
                            price_paise,
                            total_paise,
                            notes,
                        ),
                    )
            flash("Fuel record saved successfully.", "success")
            return redirect(url_for("fuel", month=month, year=year))
        except FormError as error:
            flash(str(error), "error")
    return render_fuel_page(
        month, year, record, request.form if request.method == "POST" else None
    )


@app.post("/fuel/<int:record_id>/delete")
@login_required
def delete_fuel(record_id):
    month = request.form.get("month") or request.args.get("month")
    year = request.form.get("year") or request.args.get("year")
    with get_connection() as connection:
        result = connection.execute(
            "DELETE FROM fuel_charges WHERE id = ? AND user_id = ?",
            (record_id, current_user.id),
        )
    if result.rowcount == 0:
        abort(404)
    flash("Fuel record deleted.", "success")
    if month and year:
        return redirect(url_for("fuel", month=month, year=year))
    return redirect(url_for("fuel"))


@app.route("/reports")
@login_required
def reports():
    month, year = selected_period()
    month_prefix = f"{year:04d}-{month:02d}"
    totals = monthly_totals(month, year)
    with get_connection() as connection:
        daily = connection.execute(
            """SELECT * FROM daily_expenses WHERE user_id = ?
               AND substr(expense_date, 1, 7) = ?
               ORDER BY expense_date DESC, id DESC""",
            (current_user.id, month_prefix),
        ).fetchall()
        emis = connection.execute(
            """SELECT * FROM emi WHERE status = 'Paid'
               AND user_id = ? AND substr(due_date, 1, 7) = ?
               ORDER BY due_date DESC, id DESC""",
            (current_user.id, month_prefix),
        ).fetchall()
        fuels = connection.execute(
            """SELECT * FROM fuel_charges WHERE user_id = ?
               AND substr(fuel_date, 1, 7) = ?
               ORDER BY fuel_date DESC, id DESC""",
            (current_user.id, month_prefix),
        ).fetchall()

    transactions = []
    category_totals = {}
    for row in emis:
        transactions.append(
            {
                "date": row["payment_date"] or row["due_date"],
                "type": "EMI",
                "description": row["name"],
                "category": "EMI",
                "amount_paise": row["amount_paise"],
            }
        )
        category_totals["EMI"] = category_totals.get("EMI", 0) + row["amount_paise"]
    for row in daily:
        transactions.append(
            {
                "date": row["expense_date"],
                "type": "Daily expense",
                "description": row["description"],
                "category": row["category"],
                "amount_paise": row["amount_paise"],
            }
        )
        category_totals[row["category"]] = (
            category_totals.get(row["category"], 0) + row["amount_paise"]
        )
    for row in fuels:
        transactions.append(
            {
                "date": row["fuel_date"],
                "type": "Fuel",
                "description": f'{row["vehicle_type"]} · {row["fuel_type"]}',
                "category": "Fuel",
                "amount_paise": row["total_cost_paise"],
            }
        )
        category_totals["Fuel"] = (
            category_totals.get("Fuel", 0) + row["total_cost_paise"]
        )
    transactions.sort(key=lambda item: item["date"], reverse=True)
    breakdown = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    return render_template(
        "reports.html",
        **month_context(month, year),
        totals=totals,
        salary=get_salary(month, year),
        transactions=transactions,
        breakdown=breakdown,
    )


@app.route("/reports/export.csv")
@login_required
def export_csv():
    import csv
    import io

    month, year = selected_period()
    month_prefix = f"{year:04d}-{month:02d}"
    with get_connection() as connection:
        emis = connection.execute(
            """SELECT COALESCE(payment_date, due_date) AS transaction_date, 'EMI' AS type, name AS description,
               amount_paise AS amount FROM emi
               WHERE user_id = ? AND status='Paid'
               AND substr(due_date, 1, 7)=?""",
            (current_user.id, month_prefix),
        ).fetchall()
        daily = connection.execute(
            """SELECT expense_date AS transaction_date, category AS type,
               description, amount_paise AS amount FROM daily_expenses
               WHERE user_id = ? AND substr(expense_date, 1, 7)=?""",
            (current_user.id, month_prefix),
        ).fetchall()
        fuel_rows = connection.execute(
            """SELECT fuel_date AS transaction_date, 'Fuel' AS type,
               vehicle_type || ' - ' || fuel_type AS description,
               total_cost_paise AS amount FROM fuel_charges
               WHERE user_id = ? AND substr(fuel_date, 1, 7)=?""",
            (current_user.id, month_prefix),
        ).fetchall()
    rows = sorted(
        list(emis) + list(daily) + list(fuel_rows),
        key=lambda item: item["transaction_date"],
        reverse=True,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type / Category", "Description", "Amount (INR)"])
    for row in rows:
        writer.writerow(
            [
                row["transaction_date"],
                row["type"],
                row["description"],
                f"{Decimal(row['amount']) / 100:.2f}",
            ]
        )
    filename = f"expense-report-{year:04d}-{month:02d}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5001")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
