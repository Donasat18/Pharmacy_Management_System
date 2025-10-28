import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import altair as alt
import bcrypt
import io
import uuid
import os
from typing import Optional, Any, Dict, List

# ---------- MUST BE FIRST STREAMLIT COMMAND ----------
st.set_page_config(page_title="💊 Pharmacy Management", layout="wide")

# ---------- CONFIG ----------
DB_PATH = "pharmacy.db"
APP_TITLE = "💊 Pharmacy Management"
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Configurable via environment variable

# ---------- DATABASE HELPERS ----------
def get_connection():
    """Returns a connection to the SQLite database with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    """Create schema and insert sample data if tables are empty."""
    cur = conn.cursor()
    # Users
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'staff',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Categories
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """
    )
    # Products
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER,
            quantity INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0,
            reorder_level INTEGER NOT NULL DEFAULT 10,
            supplier TEXT,
            expiry_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL
        )
        """
    )
    # Sales - No UNIQUE on invoice to allow multiple items per invoice
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            unit_cost REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL,
            sold_by INTEGER,
            sold_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(sold_by) REFERENCES users(id)
        )
        """
    )
    # Stock Adjustments
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            adjustment_qty INTEGER NOT NULL,
            reason TEXT,
            adjusted_by INTEGER,
            adjusted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(adjusted_by) REFERENCES users(id)
        )
        """
    )
    # Add indexes for optimization
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_invoice ON sales(invoice)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_adjustments_product_id ON stock_adjustments(product_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_adjustments_adjusted_at ON stock_adjustments(adjusted_at)")
    conn.commit()

    # Insert default admin if no users exist
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        pw_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt())
        cur.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            ("admin", pw_hash, "Administrator", "admin"),
        )
        conn.commit()
        print("Default admin created with username 'admin' and password from ADMIN_PASSWORD env variable or 'admin123'")

    # Insert sample categories if none exist
    cur.execute("SELECT COUNT(*) as cnt FROM categories")
    if cur.fetchone()["cnt"] == 0:
        categories = [
            ("Analgesics",), ("Antibiotics",), ("Antihistamines",), ("Antihypertensives",), ("Antidiabetics",),
            ("Antidepressants",), ("Antianxiety Agents",), ("Antivirals",), ("Antifungals",), ("Antacids & GI Drugs",),
            ("Cardiovascular Drugs",), ("Respiratory Drugs",), ("Vitamins & Supplements",), ("Hormonal Agents",),
            ("Anticoagulants",), ("Anti-inflammatory Drugs",), ("Anticonvulsants",), ("Dermatologicals",),
            ("Ophthalmic Drugs",), ("OTC Medications",),
        ]
        cur.executemany("INSERT INTO categories (name) VALUES (?)", categories)
        conn.commit()
        print("Inserted 20 sample categories")

    # Get category IDs
    cur.execute("SELECT id, name FROM categories")
    category_map = {row["name"]: row["id"] for row in cur.fetchall()}

    # Insert sample products if none exist
    cur.execute("SELECT COUNT(*) as cnt FROM products")
    if cur.fetchone()["cnt"] == 0:
        products = [
            # Analgesics (6 products)
            ("Ibuprofen 200mg", category_map["Analgesics"], 100, 5.99, 3.50, 20, "Supplier A", "2026-12-31"),
            ("Acetaminophen 500mg", category_map["Analgesics"], 150, 4.99, 2.80, 30, "Supplier B", "2026-11-15"),
            ("Aspirin 325mg", category_map["Analgesics"], 80, 3.49, 2.00, 15, "Supplier A", "2027-03-20"),
            ("Naproxen 250mg", category_map["Analgesics"], 60, 6.49, 3.90, 10, "Supplier C", "2026-09-10"),
            ("Diclofenac Gel 1%", category_map["Analgesics"], 40, 12.99, 8.00, 10, "Supplier B", "2027-01-05"),
            ("Paracetamol 650mg", category_map["Analgesics"], 120, 5.49, 3.20, 25, "Supplier A", "2026-10-30"),
            # Antibiotics (6 products)
            ("Amoxicillin 500mg", category_map["Antibiotics"], 50, 8.99, 5.50, 10, "Supplier D", "2026-08-25"),
            ("Azithromycin 250mg", category_map["Antibiotics"], 30, 10.99, 6.80, 5, "Supplier E", "2026-07-15"),
            ("Ciprofloxacin 500mg", category_map["Antibiotics"], 40, 12.49, 7.50, 10, "Supplier D", "2026-12-10"),
            ("Doxycycline 100mg", category_map["Antibiotics"], 60, 9.99, 6.00, 15, "Supplier E", "2027-02-28"),
            ("Clindamycin 300mg", category_map["Antibiotics"], 25, 15.99, 9.50, 5, "Supplier D", "2026-11-30"),
            ("Erythromycin 500mg", category_map["Antibiotics"], 35, 11.49, 7.00, 10, "Supplier E", "2026-09-30"),
            # Antihistamines (6 products)
            ("Cetirizine 10mg", category_map["Antihistamines"], 80, 6.49, 3.80, 15, "Supplier F", "2026-10-10"),
            ("Loratadine 10mg", category_map["Antihistamines"], 100, 5.99, 3.50, 20, "Supplier F", "2027-03-05"),
            ("Fexofenadine 180mg", category_map["Antihistamines"], 60, 9.99, 6.00, 10, "Supplier G", "2026-11-25"),
            ("Diphenhydramine 25mg", category_map["Antihistamines"], 70, 4.99, 2.90, 15, "Supplier F", "2026-09-20"),
            ("Chlorpheniramine 4mg", category_map["Antihistamines"], 50, 3.99, 2.30, 10, "Supplier G", "2027-02-15"),
            ("Desloratadine 5mg", category_map["Antihistamines"], 40, 10.49, 6.30, 10, "Supplier F", "2026-12-20"),
            # Antihypertensives (4 products)
            ("Lisinopril 10mg", category_map["Antihypertensives"], 90, 6.99, 4.20, 20, "Supplier H", "2026-10-20"),
            ("Amlodipine 5mg", category_map["Antihypertensives"], 100, 8.49, 5.10, 20, "Supplier H", "2027-01-25"),
            ("Losartan 50mg", category_map["Antihypertensives"], 60, 9.49, 5.70, 15, "Supplier I", "2027-03-10"),
            ("Hydrochlorothiazide 25mg", category_map["Antihypertensives"], 80, 5.49, 3.30, 15, "Supplier H", "2026-12-05"),
            # Antidiabetics (3 products)
            ("Metformin 500mg", category_map["Antidiabetics"], 100, 7.99, 4.80, 20, "Supplier J", "2027-02-15"),
            ("Glipizide 5mg", category_map["Antidiabetics"], 70, 6.99, 4.20, 15, "Supplier J", "2026-11-30"),
            ("Insulin Glargine 100U/mL", category_map["Antidiabetics"], 20, 49.99, 30.00, 5, "Supplier K", "2026-09-15"),
            # Antidepressants (3 products)
            ("Sertraline 50mg", category_map["Antidepressants"], 50, 9.99, 6.00, 10, "Supplier L", "2027-01-10"),
            ("Fluoxetine 20mg", category_map["Antidepressants"], 60, 8.49, 5.10, 10, "Supplier L", "2026-12-20"),
            ("Escitalopram 10mg", category_map["Antidepressants"], 40, 10.99, 6.60, 10, "Supplier M", "2027-03-05"),
            # Antianxiety Agents (2 products)
            ("Lorazepam 1mg", category_map["Antianxiety Agents"], 30, 11.99, 7.20, 5, "Supplier N", "2026-10-15"),
            ("Alprazolam 0.5mg", category_map["Antianxiety Agents"], 25, 12.49, 7.50, 5, "Supplier N", "2026-11-10"),
            # Antivirals (2 products)
            ("Oseltamivir 75mg", category_map["Antivirals"], 20, 29.99, 18.00, 5, "Supplier O", "2026-08-30"),
            ("Acyclovir 400mg", category_map["Antivirals"], 30, 14.99, 9.00, 5, "Supplier O", "2026-12-10"),
            # Antifungals (2 products)
            ("Fluconazole 150mg", category_map["Antifungals"], 25, 15.99, 9.60, 5, "Supplier P", "2026-11-25"),
            ("Clotrimazole Cream 1%", category_map["Antifungals"], 50, 7.99, 4.80, 10, "Supplier P", "2027-02-20"),
            # Antacids & GI Drugs (2 products)
            ("Omeprazole 20mg", category_map["Antacids & GI Drugs"], 60, 8.99, 5.40, 15, "Supplier Q", "2027-01-15"),
            ("Loperamide 2mg", category_map["Antacids & GI Drugs"], 80, 4.99, 3.00, 20, "Supplier Q", "2026-10-30"),
            # Cardiovascular Drugs (3 products)
            ("Atenolol 50mg", category_map["Cardiovascular Drugs"], 70, 7.99, 4.80, 15, "Supplier R", "2027-04-15"),
            ("Simvastatin 20mg", category_map["Cardiovascular Drugs"], 50, 8.99, 5.40, 10, "Supplier R", "2026-11-20"),
            ("Clopidogrel 75mg", category_map["Cardiovascular Drugs"], 60, 10.49, 6.30, 10, "Supplier S", "2027-03-10"),
            # Respiratory Drugs (2 products)
            ("Albuterol Inhaler 90mcg", category_map["Respiratory Drugs"], 30, 24.99, 15.00, 5, "Supplier T", "2026-09-30"),
            ("Montelukast 10mg", category_map["Respiratory Drugs"], 50, 9.99, 6.00, 10, "Supplier T", "2027-02-28"),
            # Vitamins & Supplements (6 products)
            ("Vitamin C 1000mg", category_map["Vitamins & Supplements"], 200, 4.99, 2.90, 30, "Supplier U", "2027-06-30"),
            ("Vitamin D3 2000IU", category_map["Vitamins & Supplements"], 180, 5.49, 3.20, 25, "Supplier U", "2027-05-15"),
            ("Multivitamin Tablets", category_map["Vitamins & Supplements"], 150, 6.99, 4.10, 20, "Supplier V", "2027-04-20"),
            ("Vitamin B12 500mcg", category_map["Vitamins & Supplements"], 120, 5.99, 3.50, 20, "Supplier U", "2026-12-15"),
            ("Omega-3 Fish Oil 1000mg", category_map["Vitamins & Supplements"], 100, 8.99, 5.30, 15, "Supplier V", "2027-02-10"),
            ("Calcium 600mg + D3", category_map["Vitamins & Supplements"], 90, 7.49, 4.40, 15, "Supplier U", "2027-01-30"),
            # Hormonal Agents (2 products)
            ("Levothyroxine 100mcg", category_map["Hormonal Agents"], 60, 9.49, 5.70, 10, "Supplier W", "2027-03-15"),
            ("Ethinyl Estradiol 0.03mg", category_map["Hormonal Agents"], 40, 12.99, 7.80, 10, "Supplier W", "2026-12-10"),
            # Anticoagulants (2 products)
            ("Warfarin 5mg", category_map["Anticoagulants"], 50, 8.49, 5.10, 10, "Supplier X", "2027-01-20"),
            ("Apixaban 5mg", category_map["Anticoagulants"], 30, 19.99, 12.00, 5, "Supplier X", "2026-11-30"),
            # Anti-inflammatory Drugs (2 products)
            ("Prednisone 10mg", category_map["Anti-inflammatory Drugs"], 60, 6.99, 4.20, 10, "Supplier Y", "2026-10-25"),
            ("Celecoxib 200mg", category_map["Anti-inflammatory Drugs"], 40, 13.99, 8.40, 10, "Supplier Y", "2027-02-10"),
            # Anticonvulsants (2 products)
            ("Gabapentin 300mg", category_map["Anticonvulsants"], 50, 10.99, 6.60, 10, "Supplier Z", "2026-12-15"),
            ("Levetiracetam 500mg", category_map["Anticonvulsants"], 40, 12.49, 7.50, 10, "Supplier Z", "2027-01-30"),
            # Dermatologicals (2 products)
            ("Hydrocortisone Cream 1%", category_map["Dermatologicals"], 50, 6.99, 4.20, 10, "Supplier AA", "2027-02-25"),
            ("Mupirocin Ointment 2%", category_map["Dermatologicals"], 30, 11.99, 7.20, 5, "Supplier AA", "2026-11-15"),
            # Ophthalmic Drugs (2 products)
            ("Artificial Tears 0.5%", category_map["Ophthalmic Drugs"], 60, 5.99, 3.60, 10, "Supplier BB", "2027-03-20"),
            ("Timolol Eye Drops 0.5%", category_map["Ophthalmic Drugs"], 25, 14.99, 9.00, 5, "Supplier BB", "2026-12-05"),
            # OTC Medications (2 products)
            ("Loperamide 2mg", category_map["OTC Medications"], 80, 4.99, 3.00, 20, "Supplier CC", "2026-10-30"),
            ("Acetaminophen 500mg", category_map["OTC Medications"], 150, 4.99, 2.80, 30, "Supplier CC", "2026-11-15"),
        ]
        cur.executemany(
            "INSERT OR IGNORE INTO products (name, category_id, quantity, price, cost, reorder_level, supplier, expiry_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            products
        )
        conn.commit()
        print("Inserted 51 sample products")

# ---------- AUTH HELPERS ----------
def hash_password(password: str) -> bytes:
    """Hashes a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

def _ensure_bytes(pw_hash: Any) -> bytes:
    """Converts a password hash from memoryview or str to bytes."""
    if isinstance(pw_hash, memoryview):
        return pw_hash.tobytes()
    if isinstance(pw_hash, str):
        return pw_hash.encode("utf-8")
    return pw_hash

def check_password(password: str, pw_hash: Any) -> bool:
    """Checks a plain-text password against a hashed password."""
    try:
        b = _ensure_bytes(pw_hash)
        return bcrypt.checkpw(password.encode("utf-8"), b)
    except Exception:
        return False

# ---------- DB CRUD (IMPROVED) ----------
def get_user_by_username(conn, username: str):
    """Fetches a single user by username."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username.strip(),))
    return cur.fetchone()

def list_users(conn) -> pd.DataFrame:
    """Lists all users (excluding password hash)."""
    return pd.read_sql_query("SELECT id, username, full_name, role, created_at FROM users ORDER BY username", conn)

def add_user(conn, username: str, password: str, full_name: str = "", role: str = "staff") -> bool:
    """Adds a new user to the database."""
    if not username.strip() or not password:
        raise ValueError("Username and password cannot be empty")
    if role not in ["staff", "admin"]:
        raise ValueError("Role must be 'staff' or 'admin'")
    try:
        pw_hash = hash_password(password)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                    (username.strip(), pw_hash, full_name.strip(), role))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            raise ValueError(f"Username '{username}' already exists.")
        raise

def change_user_password(conn, user_id: int, new_password: str):
    """Changes a user's password."""
    if not new_password:
        raise ValueError("New password cannot be empty")
    pw_hash = hash_password(new_password)
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
    if cur.rowcount == 0:
        raise ValueError("User ID not found.")
    conn.commit()

def update_user(conn, user_id: int, full_name: str, role: str):
    """Updates a user's full_name and role."""
    if role not in ["staff", "admin"]:
        raise ValueError("Role must be 'staff' or 'admin'")
    cur = conn.cursor()
    cur.execute("UPDATE users SET full_name=?, role=? WHERE id=?", (full_name.strip(), role, user_id))
    if cur.rowcount == 0:
        raise ValueError("User ID not found.")
    conn.commit()

def delete_user(conn, user_id: int):
    """Deletes a user, fails if associated sales or adjustments exist."""
    cur = conn.cursor()
    # Check for sales
    cur.execute("SELECT COUNT(*) as cnt FROM sales WHERE sold_by=?", (user_id,))
    if cur.fetchone()["cnt"] > 0:
        raise ValueError("Cannot delete user with associated sales history.")
    
    # Check for stock adjustments
    cur.execute("SELECT COUNT(*) as cnt FROM stock_adjustments WHERE adjusted_by=?", (user_id,))
    if cur.fetchone()["cnt"] > 0:
        raise ValueError("Cannot delete user with associated stock adjustment history.")

    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    if cur.rowcount == 0:
        raise ValueError("User ID not found.")
    conn.commit()

def list_categories(conn) -> pd.DataFrame:
    """Lists all product categories."""
    return pd.read_sql_query("SELECT * FROM categories ORDER BY name", conn)

def add_category(conn, name: str) -> bool:
    """Adds a new category."""
    if not name.strip():
        raise ValueError("Category name cannot be empty")
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO categories (name) VALUES (?)", (name.strip(),))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            raise ValueError(f"Category '{name}' already exists.")
        raise

def update_category(conn, category_id: int, new_name: str):
    """Updates the name of an existing category."""
    if not new_name.strip():
        raise ValueError("Category name cannot be empty")
    try:
        cur = conn.cursor()
        cur.execute("UPDATE categories SET name=? WHERE id=?", (new_name.strip(), category_id))
        if cur.rowcount == 0:
            raise ValueError("Category ID not found.")
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Category '{new_name}' already exists.")

def delete_category(conn, category_id: int):
    """Deletes a category, fails if products are associated."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM products WHERE category_id=?", (category_id,))
    if cur.fetchone()["cnt"] > 0:
        raise ValueError("Cannot delete category with associated products. Reassign or delete associated products first.")
    cur.execute("DELETE FROM categories WHERE id=?", (category_id,))
    if cur.rowcount == 0:
        raise ValueError("Category ID not found.")
    conn.commit()

def get_product(conn, product_id: int):
    """Fetches a single product by ID."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id=?", (product_id,))
    return cur.fetchone()

def get_products(conn) -> pd.DataFrame:
    """Lists all products with their category name."""
    q = """
    SELECT p.*, c.name as category_name
    FROM products p
    LEFT JOIN categories c ON p.category_id=c.id
    ORDER BY p.name
    """
    return pd.read_sql_query(q, conn)

def add_product(conn, name: str, category_id: Optional[int], quantity: int, price: float, cost: float, reorder_level: int, supplier: str, expiry_date: Optional[str] = None) -> int:
    """Adds a new product and records the initial stock as a stock adjustment."""
    if not name.strip():
        raise ValueError("Product name cannot be empty")
    if price < 0 or cost < 0 or quantity < 0 or reorder_level < 0:
        raise ValueError("Price, cost, quantity, and reorder level must be non-negative")
    if category_id is not None and not isinstance(category_id, int):
        raise TypeError("Category ID must be an integer or None")

    cur = conn.cursor()
    try:
        with conn:
            cur.execute(
                "INSERT INTO products (name, category_id, quantity, price, cost, reorder_level, supplier, expiry_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name.strip(), category_id, quantity, price, cost, reorder_level, supplier.strip() or None, expiry_date),
            )
            product_id = cur.lastrowid
            
            # Record initial stock as an adjustment
            if quantity > 0:
                cur.execute(
                    "INSERT INTO stock_adjustments (product_id, adjustment_qty, reason, adjusted_by) VALUES (?, ?, ?, ?)",
                    (product_id, quantity, "Initial Stock Entry", None),
                )
        return product_id
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Database error during product add: {e}")

def update_product(conn, product_id: int, name: str, category_id: Optional[int], price: float, cost: float, new_quantity: int, reorder_level: int, supplier: str, expiry_date: Optional[str] = None, adjusted_by: Optional[int] = None):
    """Updates product details, using adjust_stock if quantity changes."""
    if not name.strip():
        raise ValueError("Product name cannot be empty")
    if price < 0 or cost < 0 or new_quantity < 0 or reorder_level < 0:
        raise ValueError("Price, cost, quantity, and reorder level must be non-negative")
    if category_id is not None and not isinstance(category_id, int):
        raise TypeError("Category ID must be an integer or None")

    cur = conn.cursor()
    # 1. Get current product data
    row = get_product(conn, product_id)
    if row is None:
        raise ValueError(f"Product with ID {product_id} not found.")
    current_quantity = row["quantity"]
    
    # 2. Calculate adjustment needed
    adjustment_qty = new_quantity - current_quantity
    
    with conn:
        # Final plan: Update all fields (including quantity), then log the delta as an adjustment.
        cur.execute(
            "UPDATE products SET name=?, category_id=?, price=?, cost=?, quantity=?, reorder_level=?, supplier=?, expiry_date=? WHERE id=?",
            (name.strip(), category_id, price, cost, new_quantity, reorder_level, supplier.strip() or None, expiry_date, product_id),
        )
        
        # 4. Use adjust_stock logic if quantity has changed
        if adjustment_qty != 0:
            # Log the adjustment
            cur.execute(
                "INSERT INTO stock_adjustments (product_id, adjustment_qty, reason, adjusted_by) VALUES (?, ?, ?, ?)",
                (product_id, adjustment_qty, f"Manual Edit/Correction (New Qty: {new_quantity})", adjusted_by),
            )
    conn.commit()


def delete_product(conn, product_id: int):
    """Deletes a product, fails if associated sales exist (to maintain history). Automatically cleans up stock adjustments if no sales."""
    cur = conn.cursor()
    # Check for sales (hard block for integrity)
    cur.execute("SELECT COUNT(*) as cnt FROM sales WHERE product_id=?", (product_id,))
    if cur.fetchone()["cnt"] > 0:
        raise ValueError("Cannot delete product with associated sales history.")
    
    # If no sales, safely delete any stock adjustments first (e.g., initial entry for new products)
    cur.execute("DELETE FROM stock_adjustments WHERE product_id=?", (product_id,))
    
    # Now delete the product
    cur.execute("DELETE FROM products WHERE id=?", (product_id,))
    if cur.rowcount == 0:
        raise ValueError("Product ID not found.")
    conn.commit()

def adjust_stock(conn, product_id: int, adj_qty: int, reason: str, adjusted_by: Optional[int] = None):
    """Adjusts product stock and records the adjustment."""
    if adj_qty == 0:
        raise ValueError("Adjustment quantity cannot be zero")
    if not reason.strip():
        raise ValueError("Reason for adjustment is required")
    
    cur = conn.cursor()
    row = get_product(conn, product_id)
    if row is None:
        raise ValueError("Product not found")
        
    current_qty = row["quantity"]
    new_qty = current_qty + adj_qty
    
    if new_qty < 0:
        raise ValueError(f"Cannot adjust stock below zero (current: {current_qty}, adjustment: {adj_qty})")
        
    with conn:
        cur.execute("UPDATE products SET quantity = ? WHERE id=?", (new_qty, product_id))
        cur.execute(
            "INSERT INTO stock_adjustments (product_id, adjustment_qty, reason, adjusted_by) VALUES (?, ?, ?, ?)",
            (product_id, adj_qty, reason.strip(), adjusted_by),
        )

def get_stock_adjustments(conn, product_id: Optional[int] = None, date_from: Optional[str] = None, date_to: Optional[str] = None) -> pd.DataFrame:
    """Retrieves stock adjustment history."""
    q = """
    SELECT sa.*, p.name as product_name, u.username as adjusted_by_username
    FROM stock_adjustments sa
    LEFT JOIN products p ON sa.product_id = p.id
    LEFT JOIN users u ON sa.adjusted_by = u.id
    """
    params = []
    where_clauses = []
    if product_id is not None:
        where_clauses.append("sa.product_id = ?")
        params.append(product_id)
    if date_from and date_to:
        where_clauses.append("date(sa.adjusted_at) BETWEEN ? AND ?")
        params.extend([date_from, date_to])
    if where_clauses:
        q += " WHERE " + " AND ".join(where_clauses)
    q += " ORDER BY sa.adjusted_at DESC"
    return pd.read_sql_query(q, conn, params=tuple(params))

def generate_invoice(conn) -> str:
    """Generate a sequential invoice number for the current day."""
    today_str = date.today().strftime("%y%m%d")  # YYMMDD format
    cur = conn.cursor()
    like_pattern = f"INV-{today_str}-%"
    cur.execute("SELECT COUNT(DISTINCT invoice) FROM sales WHERE invoice LIKE ?", (like_pattern,))
    count = cur.fetchone()[0] + 1
    return f"INV-{today_str}-{count:03d}"

def record_sale(conn, invoice: str, items: List[Dict[str, Any]], sold_by: Optional[int] = None) -> float:
    """Record multiple sale items under a single invoice in a transaction."""
    cur = conn.cursor()
    totals = []
    
    if not items:
        raise ValueError("Cannot record an empty sale.")

    try:
        # Start transaction
        with conn:
            for item in items:
                product_id = item["product_id"]
                qty = item["qty"]
                unit_price = item["unit_price"]
                unit_cost = item["unit_cost"]
                
                # 'discount' is the per-unit discount amount from the cart logic
                per_unit_discount = round(item["discount"], 2) 
                final_total = round(qty * (unit_price - per_unit_discount), 2)
                
                if qty <= 0:
                    raise ValueError(f"Quantity must be positive for {item.get('product_name', 'Unknown')}")
                if final_total < 0:
                    raise ValueError(f"Total sale amount cannot be negative for {item.get('product_name', 'Unknown')}")

                # Validate stock
                cur.execute("SELECT quantity FROM products WHERE id=?", (product_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"Product ID {product_id} not found")
                avail = row["quantity"]
                if qty > avail:
                    raise ValueError(f"Only {avail} units available for {item.get('product_name', 'Unknown')}")

                # Insert sale record (FIXED: This was the source of the SyntaxError)
                cur.execute(
                    """
                    INSERT INTO sales (invoice, product_id, qty, unit_price, unit_cost, discount, total, sold_by, sold_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (invoice, product_id, qty, unit_price, unit_cost, per_unit_discount, final_total, sold_by, datetime.now().isoformat()),
                )

                # Update stock
                cur.execute("UPDATE products SET quantity = quantity - ? WHERE id=?", (qty, product_id))
                totals.append(final_total)
    except Exception as e:
        conn.rollback()
        raise e
    return sum(totals)

def undo_sale(conn, invoice: str, sold_by: Optional[int] = None):
    """Reverses a sale by invoice number, restoring stock."""
    cur = conn.cursor()
    # Fetch sales items for the invoice
    cur.execute(
        """
        SELECT product_id, qty
        FROM sales
        WHERE invoice = ?
        """,
        (invoice,)
    )
    sales = cur.fetchall()
    if not sales:
        raise ValueError(f"No sales found for invoice {invoice}")
    
    with conn:
        # Restore stock for each item
        for sale in sales:
            product_id = sale["product_id"]
            qty = sale["qty"]
            cur.execute("UPDATE products SET quantity = quantity + ? WHERE id=?", (qty, product_id))
        
        # Delete sale records
        cur.execute("DELETE FROM sales WHERE invoice = ?", (invoice,))
        if cur.rowcount == 0:
            raise ValueError(f"Sale deletion failed for invoice {invoice}. This should not happen.")
    conn.commit()

def get_sales(conn, date_from: Optional[str] = None, date_to: Optional[str] = None, product_id: Optional[int] = None, invoice: Optional[str] = None) -> pd.DataFrame:
    """Retrieves sales data with profit calculation."""
    q = """
    SELECT s.id, s.invoice, s.product_id, s.qty, s.unit_price, s.unit_cost, s.discount, s.total, s.sold_by, s.sold_at,
           p.name as product_name, u.username as sold_by_username
    FROM sales s
    LEFT JOIN products p ON s.product_id = p.id
    LEFT JOIN users u ON s.sold_by = u.id
    """
    params = []
    where_clauses = []
    if date_from and date_to:
        where_clauses.append("date(s.sold_at) BETWEEN ? AND ?")
        params.extend([date_from, date_to])
    if product_id is not None:
        where_clauses.append("s.product_id = ?")
        params.append(product_id)
    if invoice:
        where_clauses.append("s.invoice = ?")
        params.append(invoice)
    if where_clauses:
        q += " WHERE " + " AND ".join(where_clauses)
    q += " ORDER BY s.sold_at DESC"
    df = pd.read_sql_query(q, conn, params=tuple(params))
    if not df.empty:
        # Profit calculation: total_revenue - total_cost
        # s.total is the revenue after per-unit discount
        # total_cost is qty * unit_cost
        df['total_cost'] = df['qty'] * df['unit_cost']
        df['profit'] = df['total'] - df['total_cost']
        df['sold_at'] = pd.to_datetime(df['sold_at'], errors='coerce')
    else:
        # Ensure consistent column structure for empty dataframes
        df = pd.DataFrame(columns=['id', 'invoice', 'product_id', 'qty', 'unit_price', 'unit_cost', 'discount', 'total', 'sold_by', 'sold_at', 'product_name', 'sold_by_username', 'total_cost', 'profit'])
    return df

# ---------- UI HELPERS ----------
def format_currency(x: Any) -> str:
    """Formats a number as a currency string."""
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)

def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Converts a pandas DataFrame to CSV bytes."""
    return df.to_csv(index=False).encode("utf-8")

# ---------- AUTH UI (Unchanged) ----------
def login_area(conn):
    st.sidebar.header("🔐 Login")
    if "user" in st.session_state and st.session_state["user"]:
        st.sidebar.write(f"Signed in as **{st.session_state['user']['username']}** ({st.session_state['user']['role']})")
        row = get_user_by_username(conn, "admin")
        if st.session_state["user"]["username"] == "admin" and row and check_password(DEFAULT_ADMIN_PASSWORD, row["password_hash"]):
            st.sidebar.warning("Please change the default admin password in the Users section.")
        if st.sidebar.button("Sign out"):
            st.session_state.pop("user", None)
            st.session_state.pop("page", None)
            st.session_state.pop("cart", None)
            st.session_state.pop("last_sale", None)
            st.rerun()
        return True

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Sign in"):
        if not username or not password:
            st.sidebar.error("Username and password are required")
            return False
        row = get_user_by_username(conn, username)
        if row:
            if check_password(password, row["password_hash"]):
                st.session_state["user"] = {"id": row["id"], "username": row["username"], "full_name": row["full_name"], "role": row["role"]}
                st.session_state["cart"] = []
                st.session_state["last_sale"] = None
                st.sidebar.success(f"Welcome, {row['username']}")
                st.rerun()
                return True
            else:
                st.sidebar.error("Incorrect password")
        else:
            st.sidebar.error("Username not found")
    return False

# ---------- APP CONTENT (Minor UI tweaks for clarity/RBAC) ----------
def dashboard_page(conn):
    st.header("📊 Dashboard")
    feedback_container = st.container()
    page_size = 10

    # Refresh button
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 Refresh Data"):
            st.rerun()
    with col2:
        st.caption(f"Data last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Date range for sales and profit metrics
    today = date.today()
    col1, col2 = st.columns(2)
    with col1:
        d_from = st.date_input("Sales From", value=today - timedelta(days=30), key="metrics_sales_from")
    with col2:
        d_to = st.date_input("Sales To", value=today, key="metrics_sales_to")

    # Metrics
    prod_df = get_products(conn)
    prod_df['expiry_date'] = pd.to_datetime(prod_df['expiry_date'], errors='coerce')
    sales_df = get_sales(conn, d_from.isoformat(), d_to.isoformat())
    low_stock = prod_df[prod_df["quantity"] <= prod_df["reorder_level"]]
    critical_stock = prod_df[prod_df["quantity"] <= prod_df["reorder_level"] * 0.1]
    near_expiry = prod_df[(prod_df['expiry_date'] <= datetime.now() + timedelta(days=30)) & (prod_df['expiry_date'].notnull())]
    critical_expiry = prod_df[(prod_df['expiry_date'] <= datetime.now() + timedelta(days=7)) & (prod_df['expiry_date'].notnull())]
    total_sales = sales_df["total"].sum() if not sales_df.empty else 0
    total_profit = sales_df["profit"].sum() if not sales_df.empty else 0
    total_inventory_value = (prod_df['quantity'] * prod_df['cost']).sum()

    # Merge for category sales
    sales_with_cat = sales_df.merge(prod_df[['id', 'category_name']], left_on='product_id', right_on='id', how='left')

    # Alerts for critical issues
    if not critical_expiry.empty or not critical_stock.empty:
        with feedback_container:
            if not critical_expiry.empty:
                st.error(f"⚠️ **CRITICAL:** {len(critical_expiry)} product(s) expiring within 7 days!")
            if not critical_stock.empty:
                st.error(f"⚠️ **CRITICAL:** {len(critical_stock)} product(s) critically low (≤10% of reorder level)!")

    # Key Metrics - Added inventory value
    st.subheader("Key Metrics")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Low Stock Items", len(low_stock), delta_color="inverse")
    col2.metric("Critical Stock Items", len(critical_stock), delta_color="inverse")
    col3.metric("Near Expiry Items", len(near_expiry), delta_color="inverse")
    col4.metric(f"Sales ({d_from} to {d_to})", format_currency(total_sales))
    col5.metric(f"Profit ({d_from} to {d_to})", format_currency(total_profit))
    col6.metric("Total Inventory Value", format_currency(total_inventory_value))

    # Low Stock Items
    st.subheader("📦 Low Stock Items (≤ Reorder Level)")
    if not low_stock.empty:
        low_stock_display = low_stock[["id", "name", "quantity", "reorder_level", "supplier", "category_name", "expiry_date", "price", "cost"]].copy()
        # Format columns
        low_stock_display["price"] = low_stock_display["price"].apply(format_currency)
        low_stock_display["cost"] = low_stock_display["cost"].apply(format_currency)
        # Pagination
        page = st.number_input("Page", min_value=1, value=1, step=1, key="low_stock_page")
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        low_stock_paginated = low_stock_display.iloc[start_idx:end_idx]
        
        # Display Data Editor
        st.data_editor(
            low_stock_paginated,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "name": st.column_config.TextColumn("Product Name", disabled=True),
                "quantity": st.column_config.NumberColumn("Quantity", disabled=True),
                "reorder_level": st.column_config.NumberColumn("Reorder Level", disabled=True),
                "supplier": st.column_config.TextColumn("Supplier", disabled=True),
                "category_name": st.column_config.TextColumn("Category", disabled=True),
                "expiry_date": st.column_config.DateColumn("Expiry Date", disabled=True),
                "price": st.column_config.TextColumn("Price", disabled=True),
                "cost": st.column_config.TextColumn("Cost", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed"
        )
        
        # Restock buttons (Only visible if not empty)
        if st.session_state["user"]["role"] == "admin":
            st.markdown("##### Quick Actions (Admin Only)")
            cols = st.columns(min(len(low_stock_paginated), 5))
            for i, (idx, row) in enumerate(low_stock_paginated.iterrows()):
                with cols[i % 5]:
                    if st.button(f"📦 Edit {row['name'].split()[0]}", key=f"edit_{row['id']}"):
                        st.session_state["edit_product_id"] = row["id"]
                        st.session_state["page"] = "Products"
                        st.rerun()

        st.write(f"Showing {start_idx + 1}–{min(end_idx, len(low_stock))} of {len(low_stock)} items")
        csv_bytes = dataframe_to_csv_bytes(low_stock_display)
        st.download_button("📥 Export Low Stock CSV", csv_bytes, f"low_stock_{today}.csv", mime="text/csv")
    else:
        st.info("No low stock items.")

    # Near Expiry Items (Unchanged)
    st.subheader("⏰ Near Expiry Items (within 30 days)")
    if not near_expiry.empty:
        near_expiry_display = near_expiry[["id", "name", "quantity", "reorder_level", "supplier", "category_name", "expiry_date", "price", "cost"]].copy()
        near_expiry_display["price"] = near_expiry_display["price"].apply(format_currency)
        near_expiry_display["cost"] = near_expiry_display["cost"].apply(format_currency)
        page = st.number_input("Page", min_value=1, value=1, step=1, key="near_expiry_page")
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        near_expiry_paginated = near_expiry_display.iloc[start_idx:end_idx]
        st.data_editor(
            near_expiry_paginated,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "name": st.column_config.TextColumn("Product Name", disabled=True),
                "quantity": st.column_config.NumberColumn("Quantity", disabled=True),
                "reorder_level": st.column_config.NumberColumn("Reorder Level", disabled=True),
                "supplier": st.column_config.TextColumn("Supplier", disabled=True),
                "category_name": st.column_config.TextColumn("Category", disabled=True),
                "expiry_date": st.column_config.DateColumn("Expiry Date", disabled=True),
                "price": st.column_config.TextColumn("Price", disabled=True),
                "cost": st.column_config.TextColumn("Cost", disabled=True)
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed"
        )
        st.write(f"Showing {start_idx + 1}–{min(end_idx, len(near_expiry))} of {len(near_expiry)} items")
        csv_bytes = dataframe_to_csv_bytes(near_expiry_display)
        st.download_button("📥 Export Near Expiry CSV", csv_bytes, f"near_expiry_{today}.csv", mime="text/csv")
    else:
        st.info("No near-expiry items.")

    # Sales Overview (Unchanged)
    st.subheader("📈 Sales Trend")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        trend_from = st.date_input("From", value=today - timedelta(days=30), key="sales_trend_from")
    with col2:
        trend_to = st.date_input("To", value=today, key="sales_trend_to")
    with col3:
        metric = st.selectbox("Metric", ["Total Sales", "Profit"], key="sales_trend_metric")
    sales_df_filtered = get_sales(conn, trend_from.isoformat(), trend_to.isoformat())
    if not sales_df_filtered.empty:
        sales_trend = sales_df_filtered.groupby(sales_df_filtered['sold_at'].dt.date)[['total', 'profit']].sum().reset_index()
        y_field = 'total' if metric == "Total Sales" else 'profit'
        y_title = "Sales ($)" if metric == "Total Sales" else "Profit ($)"
        chart = alt.Chart(sales_trend).mark_bar().encode(
            x=alt.X('sold_at:T', title='Date'),
            y=alt.Y(f'{y_field}:Q', title=y_title, axis=alt.Axis(format='$,.2f')),
            tooltip=['sold_at:T', f'{y_field}:Q']
        ).properties(title=f"{metric} Trend")
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No sales data for the selected period.")

    # New: Sales by Category Pie Chart
    st.subheader("📊 Sales by Category")
    if not sales_df.empty and not sales_with_cat.empty:
        cat_sales = sales_with_cat.groupby('category_name')['total'].sum().reset_index()
        cat_sales = cat_sales[cat_sales['total'] > 0]  # Filter zero sales
        if not cat_sales.empty:
            pie = alt.Chart(cat_sales).mark_arc().encode(
                theta=alt.Theta('total:Q'),
                color=alt.Color('category_name:N', legend=alt.Legend(title='Category')),
                tooltip=['category_name', alt.Tooltip('total:Q', format='$,.2f')]
            ).properties(
                title='Sales Distribution by Category',
                width=400,
                height=400
            )
            st.altair_chart(pie, use_container_width=True)
        else:
            st.info("No sales data available for categories.")
    else:
        st.info("No sales data available.")

    st.subheader("Recent Sales (Latest 10)")
    if not sales_df.empty:
        sales_df_display = sales_df[["invoice", "product_name", "qty", "unit_price", "discount", "total", "profit", "sold_at", "sold_by_username"]].head(10).copy()
        sales_df_display["unit_price"] = sales_df_display["unit_price"].apply(format_currency)
        sales_df_display["discount"] = sales_df_display["discount"].apply(format_currency)
        sales_df_display["total"] = sales_df_display["total"].apply(format_currency)
        sales_df_display["profit"] = sales_df_display["profit"].apply(format_currency)
        edited_df = st.data_editor(
            sales_df_display,
            column_config={
                "invoice": st.column_config.TextColumn("Invoice", disabled=True),
                "product_name": st.column_config.TextColumn("Product", disabled=True),
                "qty": st.column_config.NumberColumn("Quantity", disabled=True),
                "unit_price": st.column_config.TextColumn("Unit Price", disabled=True),
                "discount": st.column_config.TextColumn("Discount", disabled=True),
                "total": st.column_config.TextColumn("Total", disabled=True),
                "profit": st.column_config.TextColumn("Profit", disabled=True),
                "sold_at": st.column_config.DatetimeColumn("Sold At", disabled=True),
                "sold_by_username": st.column_config.TextColumn("Sold By", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed"
        )
        if st.session_state["user"]["role"] == "admin":
            # Undo buttons are generated using the original invoice number from the full sales_df.
            recent_invoices = sales_df["invoice"].unique().tolist()[:10]
            st.markdown("##### Quick Undo (Admin Only)")
            cols = st.columns(min(len(recent_invoices), 5))
            for i, inv in enumerate(recent_invoices):
                with cols[i % 5]:
                    if st.button(f"↩️ Undo {inv}", key=f"undo_sale_recent_{inv}"):
                        try:
                            undo_sale(conn, inv, st.session_state["user"]["id"])
                            with feedback_container:
                                st.success(f"Sale for invoice {inv} undone")
                            st.rerun()
                        except ValueError as ve:
                            with feedback_container:
                                st.error(str(ve))
                        except Exception as e:
                            with feedback_container:
                                st.error(f"Failed to undo sale: {e}")
        csv_bytes = dataframe_to_csv_bytes(sales_df[['invoice', 'product_name', 'qty', 'unit_price', 'discount', 'total', 'profit', 'sold_at', 'sold_by_username']])
        st.download_button("📥 Export Sales CSV", csv_bytes, f"sales_{d_from}_{d_to}.csv", mime="text/csv")
    else:
        st.info("No recent sales.")

    st.subheader("Top 5 Products by Sales")
    if not sales_df.empty:
        top_products = sales_df.groupby("product_name")[["qty", "total", "profit"]].sum().reset_index().sort_values("total", ascending=False).head(5)
        top_products["total"] = top_products["total"].apply(format_currency)
        top_products["profit"] = top_products["profit"].apply(format_currency)
        st.data_editor(
            top_products,
            column_config={
                "product_name": st.column_config.TextColumn("Product", disabled=True),
                "qty": st.column_config.NumberColumn("Units Sold", disabled=True),
                "total": st.column_config.TextColumn("Total Sales", disabled=True),
                "profit": st.column_config.TextColumn("Total Profit", disabled=True)
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed"
        )
    else:
        st.info("No sales data available.")

    # Stock Adjustments (Unchanged)
    st.subheader("🔄 Recent Stock Adjustments")
    adj_df = get_stock_adjustments(conn).head(10)
    if not adj_df.empty:
        display_columns = ["product_name", "adjustment_qty", "reason", "adjusted_at", "adjusted_by_username"]
        st.data_editor(
            adj_df[display_columns],
            column_config={
                "product_name": st.column_config.TextColumn("Product", disabled=True),
                "adjustment_qty": st.column_config.NumberColumn("Adjustment Qty", disabled=True),
                "reason": st.column_config.TextColumn("Reason", disabled=True),
                "adjusted_at": st.column_config.DatetimeColumn("Adjusted At", disabled=True),
                "adjusted_by_username": st.column_config.TextColumn("Adjusted By", disabled=True)
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed"
        )
        csv_bytes = dataframe_to_csv_bytes(adj_df)
        st.download_button("📥 Export Adjustments CSV", csv_bytes, f"stock_adjustments_{today}.csv", mime="text/csv")
    else:
        st.info("No recent stock adjustments.")

def products_page(conn):
    st.header("📦 Products & Categories Management")
    
    prod_df = get_products(conn)
    cat_df = list_categories(conn)
    cat_map = {row["name"]: row["id"] for _, row in cat_df.iterrows()} if not cat_df.empty else {}
    is_admin = st.session_state["user"]["role"] == "admin"
    
    # --- Tabs ---
    product_tab, category_tab = st.tabs(["💊 Product Management", "📂 Category Management"])

    with product_tab:
        # --- Add product ---
        st.markdown("### ➕ Add Product")
        with st.form("add_product"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Name", key="add_name")
                category_options = ["-- none --"] + sorted(list(cat_map.keys()))
                category = st.selectbox("Category", category_options, key="add_category")
                supplier = st.text_input("Supplier", key="add_supplier")
            with col2:
                qty = st.number_input("Initial Quantity", min_value=0, value=0, key="add_qty")
                price = st.number_input("Price", min_value=0.0, value=0.0, format="%.2f", key="add_price")
                cost = st.number_input("Cost", min_value=0.0, value=0.0, format="%.2f", key="add_cost")
                reorder_level = st.number_input("Reorder Level", min_value=0, value=10, key="add_reorder")
                expiry = st.date_input("Expiry Date (optional)", value=None, key="add_expiry")
            submitted = st.form_submit_button("Add")
            if submitted:
                try:
                    expiry_str = expiry.isoformat() if expiry else None
                    category_id = cat_map.get(category) if category != "-- none --" else None
                    new_id = add_product(conn, name, category_id, int(qty), price, cost, int(reorder_level), supplier, expiry_str)
                    st.success(f"Product added with ID {new_id}")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

        # --- Search / list ---
        st.subheader("Product List")
        q = st.text_input("Search products by name or supplier")
        
        display_df = prod_df.copy()
        
        if q:
            mask = display_df["name"].str.contains(q, case=False, na=False) | display_df["supplier"].str.contains(q, case=False, na=False)
            display_df = display_df[mask]
            
        display_df["price"] = display_df["price"].apply(format_currency)
        display_df["cost"] = display_df["cost"].apply(format_currency)
        st.data_editor(
            display_df[["id", "name", "quantity", "reorder_level", "supplier", "category_name", "price", "cost", "expiry_date"]],
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic"
        )

        # --- Edit / delete ---
        st.subheader("Edit / Delete Product")
        prod_options = {f'{r["name"]} (ID:{r["id"]}, Qty:{r["quantity"]})': r["id"] for _, r in prod_df.iterrows()} if not prod_df.empty else {}
        choice = st.selectbox("Select Product", ["-- select --"] + list(prod_options.keys()))
        if choice != "-- select --":
            pid = prod_options[choice]
            row = prod_df[prod_df["id"] == pid].iloc[0]
            
            # Pre-select if coming from Dashboard
            if "edit_product_id" in st.session_state and st.session_state["edit_product_id"] == pid:
                st.session_state.pop("edit_product_id")
                st.success(f"Editing {row['name']}")
            
            with st.form("edit_product"):
                st.markdown(f"**Editing: {row['name']}**")
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("Name", value=row["name"], disabled=not is_admin)
                    category_options = ["-- none --"] + sorted(list(cat_map.keys()))
                    category_idx = 0
                    if row["category_id"] and row["category_name"]:
                        try:
                            category_idx = category_options.index(row["category_name"])
                        except ValueError:
                            pass # Category name not in current list
                    category = st.selectbox("Category", category_options, index=category_idx, disabled=not is_admin)
                    supplier = st.text_input("Supplier", value=row["supplier"] or "", disabled=not is_admin)
                    
                with col2:
                    price = st.number_input("Price", value=float(row["price"]), format="%.2f", disabled=not is_admin)
                    cost = st.number_input("Cost", value=float(row["cost"]), format="%.2f", disabled=not is_admin)
                    new_quantity = st.number_input("New Quantity", value=int(row["quantity"]), disabled=not is_admin)
                    reorder_level = st.number_input("Reorder Level", value=int(row["reorder_level"]), disabled=not is_admin)
                    expiry_val = row["expiry_date"]
                    expiry_date_val = pd.to_datetime(expiry_val).date() if pd.notnull(expiry_val) and expiry_val != 'None' else None
                    expiry = st.date_input("Expiry Date", value=expiry_date_val, disabled=not is_admin)
                    
                submitted = st.form_submit_button("Save Changes")
                if submitted:
                    if not is_admin:
                        st.error("Only Admins can modify product details.")
                    else:
                        try:
                            expiry_str = expiry.isoformat() if expiry else None
                            category_id = cat_map.get(category) if category != "-- none --" else None
                            update_product(conn, int(pid), name, category_id, price, cost, int(new_quantity), int(reorder_level), supplier, expiry_str, st.session_state["user"]["id"])
                            st.success("Product details updated")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"An unexpected error occurred: {e}")

            if is_admin:
                if st.button("🔴 Delete Product"):
                    try:
                        delete_product(conn, pid)
                        st.success("Product deleted")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")
            else:
                st.warning("Only Admins can delete products.")

    with category_tab:
        st.header("📂 Category Management")
        if not is_admin:
            st.error("You must be an Administrator to manage categories.")
            return

        options = {f"{r['name']} (ID:{r['id']})": r["id"] for _, r in cat_df.iterrows()} if not cat_df.empty else {}
        
        # --- Add Category ---
        st.subheader("➕ Add New Category")
        with st.form("add_cat_form", clear_on_submit=True):
            new_cat_name = st.text_input("Category Name")
            submitted = st.form_submit_button("Add Category")
            if submitted:
                try:
                    ok = add_category(conn, new_cat_name)
                    if ok:
                        st.success(f"Category '{new_cat_name}' added.")
                        st.rerun()
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

        # --- Existing Categories ---
        st.subheader("Existing Categories")
        st.data_editor(
            cat_df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.Column("ID", disabled=True),
                "name": st.column_config.TextColumn("Category Name", disabled=True),
            }
        )
        
        # --- EDIT/DELETE SECTION ---
        st.subheader("✏️/🔴 Edit/Delete Category")
        edit_delete_choice = st.selectbox("Select Category", ["-- select --"] + sorted(list(options.keys())), key="edit_delete_cat_select")
        
        if edit_delete_choice != "-- select --":
            cat_id = options[edit_delete_choice]
            current_name = edit_delete_choice.split(" (ID:")[0]
            
            col1, col2 = st.columns(2)
            with col1:
                with st.form("edit_cat_form"):
                    new_name = st.text_input("New Category Name", value=current_name)
                    submitted = st.form_submit_button("Update Name")
                    if submitted:
                        try:
                            update_category(conn, cat_id, new_name)
                            st.success(f"Category '{current_name}' successfully updated to '{new_name}'")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"An unexpected error occurred: {e}")
            
            with col2:
                st.warning("Deletion will fail if any products are currently assigned to this category. You must reassign or delete those products first.")
                if st.button("Delete Category"):
                    try:
                        delete_category(conn, cat_id)
                        st.success("Category deleted")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")

def users_page(conn):
    st.header("👥 Users")
    if st.session_state["user"]["role"] != "admin":
        st.error("Admin access required")
        st.stop()
        
    # List users
    users_df = list_users(conn)
    st.subheader("User List")
    st.data_editor(
        users_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "username": st.column_config.TextColumn("Username", disabled=True),
            "full_name": st.column_config.TextColumn("Full Name", disabled=True),
            "role": st.column_config.SelectboxColumn("Role", options=["staff", "admin"], disabled=True),
            "created_at": st.column_config.DatetimeColumn("Created At", disabled=True),
        }
    )
    
    # Export
    csv_bytes = dataframe_to_csv_bytes(users_df)
    st.download_button("📥 Export Users CSV", csv_bytes, "users.csv", mime="text/csv")
    
    tab1, tab2, tab3, tab4 = st.tabs(["➕ Add User", "✏️ Edit User", "🔑 Change Password", "🔴 Delete User"])
    
    with tab1:
        st.markdown("### ➕ Add User")
        with st.form("add_user"):
            col1, col2 = st.columns(2)
            with col1:
                username = st.text_input("Username")
                full_name = st.text_input("Full Name")
            with col2:
                password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                role = st.selectbox("Role", ["staff", "admin"])
            submitted = st.form_submit_button("Add")
            if submitted:
                if password != confirm_password:
                    st.error("Passwords do not match")
                else:
                    try:
                        ok = add_user(conn, username, password, full_name, role)
                        if ok:
                            st.success("User added")
                            st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")
    
    with tab2:
        st.markdown("### ✏️ Edit User")
        options = {f"{r['username']} ({r['full_name'] or 'N/A'} - {r['role']})": r['id'] for _, r in users_df.iterrows() if r['id'] != st.session_state["user"]["id"]}
        choice = st.selectbox("Select User to Edit", ["-- select --"] + list(options.keys()))
        if choice != "-- select --":
            uid = options[choice]
            user_row = users_df[users_df["id"] == uid].iloc[0]
            with st.form("edit_user"):
                col1, col2 = st.columns(2)
                with col1:
                    st.text_input("Username", value=user_row["username"], disabled=True)
                with col2:
                    role = st.selectbox("Role", ["staff", "admin"], index=0 if user_row["role"] == "staff" else 1)
                full_name = st.text_input("Full Name", value=user_row["full_name"] or "")
                submitted = st.form_submit_button("Update")
                if submitted:
                    try:
                        update_user(conn, uid, full_name, role)
                        st.success("User updated")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")
    
    with tab3:
        st.markdown("### 🔑 Change Password")
        options = {f"{r['username']} ({r['full_name'] or 'N/A'})": r['id'] for _, r in users_df.iterrows()}
        choice = st.selectbox("Select User", ["-- select --"] + list(options.keys()))
        if choice != "-- select --":
            uid = options[choice]
            with st.form(f"change_pw_{uid}"):
                new_pw = st.text_input("New Password", type="password")
                confirm_pw = st.text_input("Confirm Password", type="password")
                submitted = st.form_submit_button("Change Password")
                if submitted:
                    if new_pw != confirm_pw:
                        st.error("Passwords do not match")
                    elif not new_pw:
                        st.error("Password cannot be empty")
                    else:
                        try:
                            change_user_password(conn, uid, new_pw)
                            st.success("Password changed")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"An unexpected error occurred: {e}")
    
    with tab4:
        st.markdown("### 🔴 Delete User")
        options = {f"{r['username']} ({r['full_name'] or 'N/A'} - {r['role']})": r['id'] for _, r in users_df.iterrows() if r['id'] != st.session_state["user"]["id"]}
        choice = st.selectbox("Select User to Delete", ["-- select --"] + list(options.keys()))
        if choice != "-- select --":
            uid = options[choice]
            user_row = users_df[users_df["id"] == uid].iloc[0]
            st.warning(f"Deleting user '{user_row['username']}' ({user_row['role']}). This cannot be undone and will fail if they have associated sales or adjustments.")
            if st.button("Confirm Delete", type="primary"):
                try:
                    delete_user(conn, uid)
                    st.success("User deleted")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

def sales_page(conn):
    st.header("💰 Sales")
    prod_df = get_products(conn)
    # Rebuilding prod_map to store per-unit discount if it was somehow in the cart, 
    # but the cart handles per-unit discount amount.
    prod_map = {row["name"]: {"id": row["id"], "price": row["price"], "cost": row["cost"], "quantity": row["quantity"]} for _, row in prod_df.iterrows()} if not prod_df.empty else {}

    if "cart" not in st.session_state:
        st.session_state["cart"] = []
    if "last_sale" not in st.session_state:
        st.session_state["last_sale"] = None

    feedback_container = st.container()

    # Tabs for Sales and History
    sale_tab, history_tab = st.tabs(["🛒 Process Sales", "📈 Sales History"])

    with sale_tab:
        # Product Search and Add to Cart - Updated UX: Use widgets + button for better control and reset
        st.subheader("🛍️ Add Products to Cart")
        st.info("💡 Tip: Select a different product each time to add multiple unique items. Same product quantities will combine.")
        
        # Initialize session state for widget control if needed
        if "cart_product_idx" not in st.session_state:
            st.session_state.cart_product_idx = 0
        if "add_qty" not in st.session_state:
            st.session_state.add_qty = 1
        elif st.session_state.add_qty < 1:
            st.session_state.add_qty = 1
        if "add_disc" not in st.session_state:
            st.session_state.add_disc = 0.0
        
        product_options = ["-- select --"] + sorted([f"{row['name']} (Stock: {row['quantity']}, Price: {format_currency(row['price'])})" for _, row in prod_df.iterrows()])
        selected_product = st.selectbox(
            "Select Product",
            product_options,
            index=st.session_state.cart_product_idx,
            key="cart_product"
        )
        product_name = selected_product.split(" (")[0] if selected_product != "-- select --" else None
        
        col1, col2 = st.columns(2)
        with col1:
            qty_value = max(1, st.session_state.add_qty)
            qty = st.number_input("Qty", min_value=1, value=qty_value, step=1, key="cart_qty")
        with col2:
            discount_pct = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=st.session_state.add_disc, format="%.2f", key="cart_discount")
        
        if st.button("➕ Add to Cart", disabled=not product_name):
            try:
                if product_name not in prod_map:
                    raise ValueError("Product not found in current inventory.")
                    
                pid = prod_map[product_name]["id"]
                unit_price = prod_map[product_name]["price"]
                unit_cost = prod_map[product_name]["cost"]
                available = prod_map[product_name]["quantity"]
                
                # Discount is per-unit discount amount
                per_unit_discount = round(unit_price * (discount_pct / 100), 2)
                
                existing = next((item for item in st.session_state["cart"] if item["product_id"] == pid), None)
                
                if existing:
                    new_qty = existing["qty"] + qty
                    if new_qty > available:
                        st.error(f"Cannot exceed available stock: {available}")
                    else:
                        existing["qty"] = new_qty
                        existing["discount"] = per_unit_discount
                        st.success(f"Updated {qty} more of {product_name} (Total: {new_qty})")
                else:
                    if qty > available:
                        st.error(f"Only {available} available")
                    else:
                        st.session_state["cart"].append({
                            "product_id": pid,
                            "product_name": product_name,
                            "qty": qty,
                            "unit_price": unit_price,
                            "unit_cost": unit_cost,
                            "discount": per_unit_discount, # This is the per-unit discount amount
                            "available_qty": available
                        })
                        st.success(f"Added {qty} x {product_name}")
                
                # Reset widgets for next addition
                st.session_state.cart_product_idx = 0
                st.session_state.add_qty = 1
                st.session_state.add_disc = 0.0
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Error: {e}")

        # Cart Display and Edit
        if st.session_state["cart"]:
            st.subheader("🛒 Cart Summary")
            
            # Prepare display DataFrame
            cart_data = pd.DataFrame(st.session_state["cart"])
            cart_data['subtotal'] = cart_data['qty'] * (cart_data['unit_price'] - cart_data['discount'])
            cart_data['delete'] = False  # Add delete checkbox column
            
            # Create formatted columns for display
            display_df = cart_data[["product_name", "qty", "unit_price", "discount", "subtotal", "delete"]].copy()
            display_df["unit_price"] = display_df["unit_price"].apply(format_currency)
            display_df["discount"] = display_df["discount"].apply(format_currency)
            display_df["subtotal"] = display_df["subtotal"].apply(format_currency)
            
            # Data editor with delete checkbox
            edited_df = st.data_editor(
                display_df,
                column_config={
                    "product_name": st.column_config.TextColumn("Product", disabled=True),
                    "qty": st.column_config.NumberColumn("Quantity", disabled=True),
                    "unit_price": st.column_config.TextColumn("Unit Price", disabled=True),
                    "discount": st.column_config.TextColumn("Discount per unit", disabled=True),
                    "subtotal": st.column_config.TextColumn("Subtotal", disabled=True),
                    "delete": st.column_config.CheckboxColumn("Select to Delete", default=False),
                },
                use_container_width=True,
                hide_index=True,
                num_rows="fixed"
            )
            
            # Remove selected items button
            if st.button("🗑️ Remove Selected Items"):
                selected_rows = edited_df[edited_df['delete'] == True].index.tolist()
                if selected_rows:
                    # Remove from cart in reverse order to preserve indices
                    for idx in sorted(selected_rows, reverse=True):
                        del st.session_state["cart"][idx]
                    st.success(f"Removed {len(selected_rows)} item(s) from cart.")
                    st.rerun()
                else:
                    st.warning("No items selected for removal.")
            
            # Calculate and display grand total
            unformatted_cart_df = pd.DataFrame(st.session_state["cart"])
            grand_total = (unformatted_cart_df["qty"] * (unformatted_cart_df["unit_price"] - unformatted_cart_df["discount"])).sum()
            st.markdown(f"**Grand Total: {format_currency(grand_total)}**")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("🗑️ Clear Entire Cart"):
                    st.session_state["cart"] = []
                    st.rerun()
            with col2:
                pass  # Placeholder for future actions
            with col3:
                # Checkout
                if grand_total > 0:
                    with st.popover("Complete Sale"):
                        with st.form("checkout"):
                            invoice = st.text_input("Invoice Number", value=generate_invoice(conn), key="invoice_num")
                            customer_name = st.text_input("Customer Name (optional)")
                            notes = st.text_area("Notes (optional)")
                            submitted = st.form_submit_button(f"💳 Complete Sale for {format_currency(grand_total)}")
                            if submitted:
                                try:
                                    sold_by = st.session_state["user"]["id"]
                                    # Copy cart before recording
                                    last_sale_items = st.session_state["cart"].copy()
                                    total_amount = record_sale(conn, invoice, st.session_state["cart"], sold_by)
                                    st.session_state["last_sale"] = {
                                        "invoice": invoice,
                                        "total": total_amount,
                                        "customer": customer_name,
                                        "notes": notes,
                                        "items": last_sale_items
                                    }
                                    st.session_state["cart"] = []
                                    st.success(f"Sale completed! Invoice: {invoice}, Total: {format_currency(total_amount)}")
                                    st.info("💡 Sale recorded! Navigate to Dashboard to see live metrics (stock updated, sales reflected).")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Sale failed: {e}")
                else:
                    st.warning("Grand Total is zero. Cannot complete sale.")


            # Last Sale Receipt - Updated to show items
            if st.session_state["last_sale"]:
                st.subheader("🧾 Last Sale Receipt")
                st.write(f"**Invoice #:** {st.session_state['last_sale']['invoice']}")
                st.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                if st.session_state['last_sale'].get('customer'):
                    st.write(f"**Customer:** {st.session_state['last_sale']['customer']}")
                
                # Items table
                if "items" in st.session_state["last_sale"] and st.session_state["last_sale"]["items"]:
                    receipt_items = st.session_state["last_sale"]["items"].copy()
                    receipt_df = pd.DataFrame(receipt_items)
                    receipt_df["line_total"] = receipt_df["qty"] * (receipt_df["unit_price"] - receipt_df["discount"])
                    receipt_df["unit_price"] = receipt_df["unit_price"].apply(format_currency)
                    receipt_df["discount"] = receipt_df["discount"].apply(lambda x: f"${x:.2f}/unit")
                    receipt_df["line_total"] = receipt_df["line_total"].apply(format_currency)
                    st.subheader("Items:")
                    st.table(receipt_df[["product_name", "qty", "unit_price", "discount", "line_total"]])
                
                st.markdown("---")
                st.write(f"**Grand Total:** {format_currency(st.session_state['last_sale']['total'])}")
                if st.session_state['last_sale'].get('notes'):
                    st.write(f"**Notes:** {st.session_state['last_sale']['notes']}")
                
                # Undo
                if st.button("↩️ Undo Last Sale (Admin Only)", disabled=st.session_state["user"]["role"] != "admin"):
                    if st.session_state["user"]["role"] == "admin":
                        try:
                            undo_sale(conn, st.session_state["last_sale"]["invoice"], st.session_state["user"]["id"])
                            st.session_state.pop("last_sale")
                            st.success("Sale undone")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Undo failed: {e}")
                    else:
                        st.error("Only Admins can undo sales.")
                
                # New: Auto-suggest navigating to Dashboard after sale
                if st.button("📊 View Updated Dashboard"):
                    st.session_state["page"] = "Dashboard"
                    st.rerun()
        else:
            st.info("Cart is empty. Add products to start.")

    with history_tab:
        st.subheader("Sales History")
        col1, col2 = st.columns(2)
        with col1:
            hist_from = st.date_input("From", value=date.today() - timedelta(days=30))
        with col2:
            hist_to = st.date_input("To", value=date.today())
        search = st.text_input("Search by Product or Invoice")
        hist_df = get_sales(conn, hist_from.isoformat(), hist_to.isoformat())
        if search:
            hist_df = hist_df[hist_df["product_name"].str.contains(search, case=False, na=False) | hist_df["invoice"].str.contains(search, case=False, na=False)]
        
        if not hist_df.empty:
            # Group by invoice for summary
            grouped = hist_df.groupby("invoice").agg({
                "product_name": lambda x: " | ".join(x),
                "total": "sum",
                "sold_at": "first",
                "sold_by_username": "first"
            }).reset_index()
            grouped.rename(columns={"product_name": "Items", "sold_by_username": "Sold By"}, inplace=True)
            grouped["total"] = grouped["total"].apply(format_currency)
            
            st.data_editor(
                grouped[["invoice", "Items", "total", "sold_at", "Sold By"]].sort_values("sold_at", ascending=False), 
                use_container_width=True,
                hide_index=True
            )
            csv_bytes = dataframe_to_csv_bytes(hist_df)
            st.download_button("Export CSV (Detailed)", csv_bytes, f"sales_history_{hist_from}_{hist_to}.csv")
        else:
            st.info("No sales found.")

def main():
    conn = get_connection()
    init_db(conn)
    if login_area(conn):
        page_names_to_funcs = {
            "Products": products_page,
            "Sales": sales_page,
        }
        if st.session_state["user"]["role"] == "admin":
            page_names_to_funcs.update({
                "Dashboard": dashboard_page,
                "Users": users_page
            })
        
        st.sidebar.title(APP_TITLE)
        
        # Determine the selected page, prioritizing a rerouted page
        if "page" in st.session_state:
            selected_page = st.session_state.pop("page")
            # If the rerouted page is for admin and the user is not admin, default to Products
            if selected_page in ["Dashboard", "Users"] and st.session_state["user"]["role"] != "admin":
                selected_page = "Products"
        else:
            # Default or sidebar selection
            selected_page = st.sidebar.selectbox("Navigate", list(page_names_to_funcs.keys()))

        page_func = page_names_to_funcs[selected_page]
        page_func(conn)
    else:
        st.title(APP_TITLE)
        st.info("Please log in to access the system.")
    conn.close()

if __name__ == "__main__":
    main()