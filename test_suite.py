"""Comprehensive automated test suite for Personal Expense Tracker."""

import re
from datetime import date
from app import app
from database import get_connection, get_session, User
from werkzeug.security import generate_password_hash

app.config["WTF_CSRF_ENABLED"] = False
app.config["TESTING"] = True

def run_tests():
    print("====================================================")
    print("RUNNING COMPREHENSIVE EXPENSE TRACKER TEST SUITE")
    print("====================================================")

    with app.test_client() as client:
        # Setup test user
        with get_session() as session:
            user = session.query(User).filter_by(email="tracker_test@example.com").first()
            if not user:
                user = User(email="tracker_test@example.com", password_hash=generate_password_hash("securepass123"))
                session.add(user)
                session.commit()
            user_id = user.id

        # Clean slate for test user
        with get_connection() as conn:
            conn.execute("DELETE FROM salary WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM emi WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM daily_expenses WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM fuel_charges WHERE user_id = ?", (user_id,))

        # 1. Unauthenticated redirects
        res = client.get("/")
        assert res.status_code == 302 and "/dashboard" in res.headers["Location"], "Root should redirect to dashboard"
        res = client.get("/dashboard")
        assert res.status_code == 302 and "/login" in res.headers["Location"], "Dashboard should require login"
        print("[PASS] 1. Unauthenticated routes properly protected")

        # 2. Login
        res = client.post("/login", data={"email": "tracker_test@example.com", "password": "wrongpassword"}, follow_redirects=True)
        assert b"Email or password is incorrect" in res.data, "Invalid credentials should flash error"
        res = client.post("/login", data={"email": "tracker_test@example.com", "password": "securepass123"}, follow_redirects=True)
        assert res.status_code == 200 and res.request.path == "/dashboard", "Valid credentials should log in"
        print("[PASS] 2. User authentication and session management")

        # 3. Add Salary
        res = client.post("/salary", data={
            "month": 11,
            "year": 2026,
            "amount": "80000.00",
            "received": "yes",
            "notes": "Software Engineer Salary"
        }, follow_redirects=True)
        assert res.status_code == 200
        assert b"80,000.00" in res.data
        print("[PASS] 3. Salary recorded and rendered")

        # 4. Add EMIs (One paid, one unpaid)
        res = client.post("/emi", data={
            "name": "Apartment Loan",
            "amount": "28500",
            "due_date": "2026-11-10",
            "status": "Paid",
            "payment_date": "2026-11-05",
            "notes": "SBI Home Loan",
            "month": 11,
            "year": 2026
        }, follow_redirects=True)
        assert res.status_code == 200

        res = client.post("/emi", data={
            "name": "Laptop EMI",
            "amount": "5200",
            "due_date": "2026-11-25",
            "status": "Unpaid",
            "payment_date": "",
            "notes": "No cost EMI",
            "month": 11,
            "year": 2026
        }, follow_redirects=True)
        assert res.status_code == 200
        print("[PASS] 4. EMIs (Paid and Unpaid) recorded successfully")

        # 5. Add Daily Expenses
        res = client.post("/expenses", data={
            "expense_date": "2026-11-01",
            "category": "Food",
            "description": "Monthly Grocery Run",
            "amount": "6400",
            "payment_method": "UPI",
            "month": 11,
            "year": 2026
        }, follow_redirects=True)
        assert res.status_code == 200

        res = client.post("/expenses", data={
            "expense_date": "2026-11-04",
            "category": "Bills",
            "description": "Fiber Internet",
            "amount": "1200",
            "payment_method": "Card",
            "month": 11,
            "year": 2026
        }, follow_redirects=True)
        assert res.status_code == 200
        print("[PASS] 5. Daily Expenses recorded successfully")

        # 6. Add Fuel Charge
        res = client.post("/fuel", data={
            "fuel_date": "2026-11-03",
            "vehicle_type": "Car",
            "fuel_type": "Petrol",
            "quantity_litres": "35",
            "price_per_litre": "103.50",
            "total_cost": "3622.50",
            "notes": "BPCL Highway",
            "month": 11,
            "year": 2026
        }, follow_redirects=True)
        assert res.status_code == 200
        print("[PASS] 6. Fuel charges recorded with volume and rate")

        # 7. Test Dashboard Calculations
        # Total Outflow = 28500 (EMI) + 6400 (Food) + 1200 (Bills) + 3622.50 (Fuel) = 39722.50
        # Remaining = 80000 - 39722.50 = 40277.50
        res = client.get("/dashboard?month=2026-11")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "80,000.00" in html, "Salary should be present on dashboard"
        assert "28,500.00" in html, "Paid EMI should be present"
        assert "7,600.00" in html, "Daily expenses (6400 + 1200) should equal 7,600.00"
        assert "3,622.50" in html, "Fuel expenses should be 3,622.50"
        assert "39,722.50" in html, "Total expenses should equal 39,722.50"
        assert "40,277.50" in html, "Remaining balance should equal 40,277.50"
        print("[PASS] 7. Dashboard financial calculations 100% verified")

        # 8. Test EMI Quick Toggle Status
        with get_connection() as conn:
            laptop_emi = conn.execute("SELECT id FROM emi WHERE user_id = ? AND name = 'Laptop EMI'", (user_id,)).fetchone()
        
        # Toggle from Unpaid -> Paid
        res = client.post(f"/emi/{laptop_emi['id']}/toggle-status", data={"month": 11, "year": 2026}, follow_redirects=True)
        assert res.status_code == 200
        with get_connection() as conn:
            new_st = conn.execute("SELECT status, payment_date FROM emi WHERE id = ?", (laptop_emi['id'],)).fetchone()
        assert new_st["status"] == "Paid", "Status should flip to Paid"
        assert new_st["payment_date"] is not None, "Payment date should be populated"

        # Toggle back Paid -> Unpaid
        client.post(f"/emi/{laptop_emi['id']}/toggle-status", data={"month": 11, "year": 2026}, follow_redirects=True)
        with get_connection() as conn:
            reverted = conn.execute("SELECT status, payment_date FROM emi WHERE id = ?", (laptop_emi['id'],)).fetchone()
        assert reverted["status"] == "Unpaid"
        assert reverted["payment_date"] is None
        print("[PASS] 8. 1-click EMI status toggle feature operates seamlessly")

        # 9. Test Expense Keyword Search and Filtering
        res = client.get("/expenses?month=2026-11&q=Grocery")
        assert res.status_code == 200
        assert b"Monthly Grocery Run" in res.data
        assert b"Fiber Internet" not in res.data

        res = client.get("/expenses?month=2026-11&category=Bills")
        assert res.status_code == 200
        assert b"Fiber Internet" in res.data
        assert b"Monthly Grocery Run" not in res.data
        print("[PASS] 9. Expense search by description and category filter verified")

        # 10. Test Reports & CSV Export
        res = client.get("/reports?month=2026-11")
        assert res.status_code == 200
        assert b"Financial Statement" in res.data
        assert b"39,722.50" in res.data

        res = client.get("/reports/export.csv?month=2026-11")
        assert res.status_code == 200
        assert res.headers["Content-Type"].startswith("text/csv")
        csv_text = res.data.decode("utf-8-sig")
        assert "Apartment Loan" in csv_text
        assert "Monthly Grocery Run" in csv_text
        assert "3622.50" in csv_text
        print("[PASS] 10. Reports calculation and UTF-8 BOM CSV export verified")

        # 11. Test Month-Preserving Deletes
        with get_connection() as conn:
            food_exp = conn.execute("SELECT id FROM daily_expenses WHERE user_id = ? AND category = 'Food'", (user_id,)).fetchone()
        res = client.post(f"/expenses/{food_exp['id']}/delete", data={"month": 11, "year": 2026}, follow_redirects=False)
        assert res.status_code == 302
        assert "month=11" in res.headers["Location"] and "year=2026" in res.headers["Location"], "Delete must preserve month/year navigation"
        print("[PASS] 11. Deletions accurately preserve month/year context")

    print("====================================================")
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    print("====================================================")

if __name__ == "__main__":
    run_tests()

