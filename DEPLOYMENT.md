# Deploying the Personal Expense Tracker

## What caused the local deployment failure

The inspected project created and queried `instance/expenses.db` during app
startup. That is a local SQLite file, not a persistent database for Vercel
functions; their writable filesystem is temporary. It also kept static files
under Flask's `static/` directory, while Vercel's Flask deployment serves
static assets from `public/`. Those are concrete deployment defects. The
project did not have a `vercel.json`, but Vercel supports a Flask instance in
root `app.py`, so the absence of that file alone is not necessarily an error.
The runtime log is unavailable, so the exact exception behind the reported
HTTP 500 cannot be confirmed without it.

The local SQLite database inspected during this change had zero salary, EMI,
daily expense, and fuel rows. Its columns have been carried into the
PostgreSQL schema, along with an account owner for each financial record.

## 1. Create a Supabase PostgreSQL database

1. Create a Supabase project.
2. In Supabase, open **Project Settings → Database → Connection string**.
3. Select the **Transaction pooler** connection string and copy its URI. Use the
   database password you set for the Supabase project. If the password contains
   reserved URL characters, percent-encode them before putting it in the URI.
4. Keep this URI private. The application uses the database connection directly;
   it does not need the Supabase `anon` key or `service_role` key.

The app turns `postgresql://` into the SQLAlchemy psycopg driver URL, requires
SSL, and disables psycopg prepared statements for compatibility with the
Supabase transaction pooler.

## 2. Configure Vercel

1. Push the project to a Git provider connected to Vercel.
2. In Vercel, set **Root Directory** to `personal_expense_tracker` if the
   project folder is inside a larger repository. If this folder itself is the
   repository root, leave the root directory as `.`. It must be the folder
   containing `app.py`, `requirements.txt`, and `public/`.
3. Under **Project → Settings → Environment Variables**, add these variables
   for Production (and Preview if you use preview deployments):

   | Name | Value |
   | --- | --- |
   | `DATABASE_URL` | The Supabase PostgreSQL transaction-pooler URI |
   | `SECRET_KEY` | A long, random secret; generate one with `py -3 -c "import secrets; print(secrets.token_hex(32))"` |

4. Save the variables and redeploy. Vercel recognizes the root `app.py` Flask
   instance and `.python-version` selects Python 3.12. The existing CSS and
   JavaScript are served from `public/static/`. Missing production database or
   session-secret variables cause a clear startup error instead of silently
   using ephemeral SQLite or a public default secret.
5. On the first app start, SQLAlchemy creates the required tables. Open the
   public deployment URL, register an account, and log in.

Do not put the database URI, Supabase database password, or generated secret in
source code. Do not commit `.env` files or `instance/expenses.db`.

## 3. Check database connectivity

From the project directory, set the same database URL and a local secret in
PowerShell, then run the check command:

```powershell
$env:DATABASE_URL = "paste-your-Supabase-connection-URI-here"
$env:SECRET_KEY = "paste-a-long-random-secret-here"
.\.venv\Scripts\flask.exe --app app check-db
```

Successful output is `Database connection OK (postgresql).` A connection error
means the URI, password, network access, or Supabase project needs attention;
it does not indicate that a Vercel deployment succeeded.

## 4. Import any local SQLite records

The current local SQLite database has no records, so there is currently
nothing to import. If you have added local records since it was inspected:

1. Deploy the app and register the account that should own those records.
2. From the project folder on the computer that contains
   `instance/expenses.db`, set `DATABASE_URL` to the same Supabase URI and run:

   ```powershell
   $env:DATABASE_URL = "paste-your-Supabase-connection-URI-here"
   $env:SECRET_KEY = "paste-a-long-random-secret-here"
   .\.venv\Scripts\flask.exe --app app migrate-sqlite --email you@example.com
   ```

3. The command copies the existing salary, EMI, daily-expense, and fuel rows to
   that registered account. It preserves their record IDs and fields, skips IDs
   already present in the destination, and reports the number imported. Keep a
   backup of the SQLite file until you confirm the imported records in the site.

For PostgreSQL records created before account ownership was added, use
`claim-unassigned-records --email you@example.com` only when you have verified
that all unassigned records belong to that account.

## Local development

Without `DATABASE_URL`, the app continues to use the local
`instance/expenses.db` SQLite file. Install dependencies with
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then run
`.\.venv\Scripts\python.exe app.py` and open `http://127.0.0.1:5001`.
