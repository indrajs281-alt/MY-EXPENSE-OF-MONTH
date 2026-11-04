/**
 * Personal Expense Tracker - Interactive UI Scripts
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Mobile Menu Drawer & Backdrop
    const menuToggle = document.getElementById("menu-toggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");

    function closeSidebar() {
        if (sidebar) sidebar.classList.remove("sidebar-open");
        if (backdrop) backdrop.classList.remove("active");
        if (menuToggle) menuToggle.classList.remove("active");
    }

    function openSidebar() {
        if (sidebar) sidebar.classList.add("sidebar-open");
        if (backdrop) backdrop.classList.add("active");
        if (menuToggle) menuToggle.classList.add("active");
    }

    if (menuToggle && sidebar) {
        menuToggle.addEventListener("click", () => {
            if (sidebar.classList.contains("sidebar-open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    if (backdrop) {
        backdrop.addEventListener("click", closeSidebar);
    }

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeSidebar();
        }
    });

    // 2. Flash Notifications Auto-dismiss & Manual Close
    document.querySelectorAll(".flash").forEach((flash) => {
        const closeBtn = flash.querySelector(".flash-close");
        if (closeBtn) {
            closeBtn.addEventListener("click", () => {
                flash.style.opacity = "0";
                flash.style.transform = "translateY(-8px)";
                flash.style.transition = "all 0.25s ease";
                setTimeout(() => flash.remove(), 250);
            });
        }

        // Auto-dismiss after 6 seconds for success messages
        if (flash.classList.contains("flash-success")) {
            setTimeout(() => {
                if (flash.parentElement) {
                    flash.style.opacity = "0";
                    flash.style.transform = "translateY(-8px)";
                    flash.style.transition = "all 0.4s ease";
                    setTimeout(() => flash.remove(), 400);
                }
            }, 5500);
        }
    });

    // 3. Password Visibility Toggle
    const passwordToggle = document.getElementById("password-toggle");
    const passwordInput = document.getElementById("password");
    if (passwordToggle && passwordInput) {
        passwordToggle.addEventListener("click", () => {
            const isPassword = passwordInput.getAttribute("type") === "password";
            passwordInput.setAttribute("type", isPassword ? "text" : "password");
            passwordToggle.classList.toggle("showing", isPassword);
            passwordToggle.setAttribute(
                "aria-label",
                isPassword ? "Hide password" : "Show password"
            );
        });
    }

    // 4. Form Submission Confirmations
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const message = form.dataset.confirm || "Are you sure you want to proceed?";
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    // 5. Form Validation
    document.querySelectorAll("form[data-validate]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!form.reportValidity()) {
                event.preventDefault();
            }
        });
    });

    // 6. Fuel Calculator (Litres * Price = Total)
    const quantity = document.getElementById("quantity_litres");
    const price = document.getElementById("price_per_litre");
    const total = document.getElementById("total_cost");

    if (quantity && price && total) {
        const updateFuelTotal = () => {
            const litres = parseFloat(quantity.value);
            const perLitre = parseFloat(price.value);

            if (!isNaN(litres) && litres > 0 && !isNaN(perLitre) && perLitre > 0) {
                total.value = (litres * perLitre).toFixed(2);
                total.readOnly = true;
                total.style.backgroundColor = "#f1f5f9";
            } else {
                total.readOnly = false;
                total.style.backgroundColor = "#ffffff";
            }
        };

        quantity.addEventListener("input", updateFuelTotal);
        price.addEventListener("input", updateFuelTotal);
        updateFuelTotal();
    }

    // 7. Client-Side Instant Table Search (Reports & Transactions)
    const txSearch = document.getElementById("transaction-search");
    const txTable = document.getElementById("transactions-table");

    if (txSearch && txTable) {
        txSearch.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            const rows = txTable.querySelectorAll("tbody tr");

            rows.forEach((row) => {
                const text = row.textContent.toLowerCase();
                if (text.includes(query)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        });
    }

    // 8. Dynamic Progress Bar & Chart Widths
    document.querySelectorAll("[data-width]").forEach((el) => {
        const widthVal = el.getAttribute("data-width");
        if (widthVal) {
            el.style.width = widthVal;
        }
    });
});
