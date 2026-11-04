# ExpenseTracker · Personal Finance Management

A modern, high-precision personal expense tracker web application built with Python, Flask, SQLAlchemy, and SQLite/PostgreSQL. Designed to manage your monthly salary, recurring EMI obligations, daily expenses, and vehicle fuel costs with integer-precise calculations and financial reporting.

---

## Key Features

- **Modern Fintech UI & UX**: Clean, responsive layout crafted with Plus Jakarta Sans & Inter typography, SVG iconography, smooth drawer navigation, and light/dark accents.
- **Monthly Overview Dashboard**:
  - Live budget gauge showing percentage of salary spent.
  - 6 metric cards: Monthly Salary, Paid EMI, Daily Expenses, Fuel Charges, Total Outflow, and Remaining Balance.
  - Interactive expense distribution bar (EMI vs Daily vs Fuel).
  - Pending EMI reminders with countdowns (e.g., *Due in 3 days*, *Overdue*).
  - Recent spending activity feed with category tags.
- **Fast Period Navigation**:
  - Previous (`‹`) and Next (`›`) month navigator buttons across all views.
  - One-click "This Month" button.
- **Salary & Income Management**:
  - Record and edit in-hand monthly salary with "Received" vs "Pending" confirmation.
  - Full salary history table with quick edit and deletion.
- **EMI & Debt Obligation Tracker**:
  - Track loans, device installments, and recurring dues with due dates and payment dates.
  - **1-Click Status Toggle**: Mark EMIs as Paid or Unpaid right from the table row.
  - Only *Paid* EMIs count toward monthly expense totals; upcoming ones are tracked without double charging your balance.
- **Daily Expenses**:
  - Categorized spending (Food, Shopping, Travel, Rent, Bills, Medical, Entertainment, Other).
  - Real-time text search by description and date range filters.
  - Multiple payment methods (UPI, Cash, Card, Other).
- **Vehicle Fuel Tracker**:
  - Log vehicle type (Car, Bike, Scooter, Other) and fuel type (Petrol, Diesel, CNG).
  - Automatic calculation of total cost from quantity and rate per litre.
- **Monthly Reports & CSV Export**:
  - Category breakdown with visual progress bars and percentage share.
  - Financial insights: Average daily outflow, savings rate (%).
  - Searchable transaction history with 1-click **Export CSV** (UTF-8 BOM compatible with Microsoft Excel).
  - Print / Save as PDF view.
- **Security & Privacy**:
  - Multi-user authentication with hashed passwords (PBKDF2/SHA256).
  - Cross-Site Request Forgery (CSRF) protection on all POST requests.
  - HTTP-only, SameSite session cookies with security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`).
  - Strict isolation: each user's financial records are private to their account.

---

## Getting Started

### 1. Prerequisites
- Python 3.10+ (Python 3.12 or 3.13 recommended)

### 2. Setup Virtual Environment & Install Dependencies

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

### 3. Run the Application Locally

```powershell
python app.py
```

Open your browser and navigate to:
```
http://127.0.0.1:5001
```

### 4. Running Automated Tests

```powershell
python test_suite.py
```

---

## Production Deployment (Vercel + Supabase PostgreSQL)

See [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step instructions on connecting a Supabase PostgreSQL database and deploying to Vercel.
