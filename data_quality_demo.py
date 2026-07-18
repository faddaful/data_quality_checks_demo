"""
  DATA QUALITY CHECKS IN PYTHON — NO TOOLS NEEDED
    This demo shows how to implement a simple data quality framework
"""

from typing import Any, Optional
import duckdb
from duckdb import DuckDBPyConnection

# SECTION 1: SETUP — Create realistic sample data

def setup_demo_database(conn: DuckDBPyConnection) -> None:
    """Create a realistic orders table for our demo."""
    conn.execute("""
        CREATE TABLE orders (
            order_id    INTEGER,
            customer_id INTEGER,
            product     VARCHAR,
            status      VARCHAR,
            amount      DOUBLE,
            email       VARCHAR,
            created_at  DATE
        )
    """)

    conn.execute("""
        INSERT INTO orders VALUES
            (1001, 1, 'Laptop',     'completed', 1200.00, 'alice@email.com',  '2024-01-01'),
            (1002, 2, 'Phone',      'pending',    800.00, 'bob@email.com',    '2024-01-02'),
            (1003, 3, 'Tablet',     'completed',  450.00, 'carol@email.com',  '2024-01-03'),
            (1004, 4, 'Headphones', 'shipped',    200.00, 'dave@email.com',   '2024-01-04'),
            (1005, 5, 'Monitor',    'refunded',   350.00, 'eve@email.com',    '2024-01-05'),
            -- BAD DATA below
            (1006, 6, 'Laptop',     'DELETED',    900.00, 'frank@email.com',  '2024-01-06'),  -- invalid status
            (1007, 7, 'Phone',      'completed',   -50.00, 'ghost@email.com', '2024-01-07'),  -- negative amount
            (1008, 8, 'Tablet',      NULL,         300.00, 'hana@email.com',  '2024-01-08'),  -- null status
            (1001, 9, 'Keyboard',   'completed',   120.00, 'ivan@email.com',  '2024-01-09'),  -- duplicate order_id
            (1010, 10,'Mouse',      'pending',     80.00,  'not-an-email',    '2024-01-10')   -- bad email
    """)
    conn.commit()
    print("Demo database ready with 10 orders (some intentionally bad!)\n")


# SECTION 2: THE CORE PATTERN
#   "Write a SQL query that selects rows which FAIL the check."
#   If 0 rows come back, it means the check PASSED. Simple!

# ─────────────────────────────────────────────
# CHECK 1: Column values in allowed set
# ─────────────────────────────────────────────
def check_values_in_set(
    conn: DuckDBPyConnection,
    table_name: str,
    column_name: str,
    allowed_values: list[str],
) -> bool:
    """PASS if every value in column_name is within allowed_values."""
    placeholders = ", ".join(f"'{v}'" for v in allowed_values)
    sql = f"""
        SELECT *
        FROM   {table_name}
        WHERE  {column_name} NOT IN ({placeholders})
           OR  {column_name} IS NULL
        LIMIT 1
    """
    rows = conn.sql(sql).fetchall()
    return len(rows) == 0


# ─────────────────────────────────────────────
# CHECK 2: No nulls in a column
# ─────────────────────────────────────────────
def check_not_null(
    conn: DuckDBPyConnection,
    table_name: str,
    column_name: str,
) -> bool:
    """PASS if column_name contains zero NULL values."""
    sql = f"SELECT 1 FROM {table_name} WHERE {column_name} IS NULL LIMIT 1"
    rows = conn.sql(sql).fetchall()
    return len(rows) == 0


# ─────────────────────────────────────────────
# CHECK 3: Column values are unique
# ─────────────────────────────────────────────
def check_unique(
    conn: DuckDBPyConnection,
    table_name: str,
    column_name: str,
) -> bool:
    """PASS if column_name has no duplicate values."""
    sql = f"""
        SELECT {column_name}
        FROM   {table_name}
        GROUP BY {column_name}
        HAVING COUNT(*) > 1
        LIMIT 1
    """
    rows = conn.sql(sql).fetchall()
    return len(rows) == 0


# ─────────────────────────────────────────────
# CHECK 4: Numeric values within a range
# ─────────────────────────────────────────────
def check_value_range(
    conn: DuckDBPyConnection,
    table_name: str,
    column_name: str,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> bool:
    """PASS if all numeric values fall within [min_val, max_val]."""
    conditions = []
    if min_val is not None:
        conditions.append(f"{column_name} < {min_val}")
    if max_val is not None:
        conditions.append(f"{column_name} > {max_val}")
    if not conditions:
        return True
    sql = f"SELECT 1 FROM {table_name} WHERE {' OR '.join(conditions)} LIMIT 1"
    rows = conn.sql(sql).fetchall()
    return len(rows) == 0


# ─────────────────────────────────────────────
# CHECK 5: Regex pattern match
# ─────────────────────────────────────────────
def check_regex_pattern(
    conn: DuckDBPyConnection,
    table_name: str,
    column_name: str,
    pattern: str,
) -> bool:
    """PASS if all non-null values in column_name match the regex pattern."""
    sql = f"""
        SELECT 1
        FROM   {table_name}
        WHERE  {column_name} IS NOT NULL
          AND  NOT regexp_matches({column_name}, '{pattern}')
        LIMIT 1
    """
    rows = conn.sql(sql).fetchall()
    return len(rows) == 0


# ─────────────────────────────────────────────
# CHECK 6: Row count within expected range
# ─────────────────────────────────────────────
def check_row_count(
    conn: DuckDBPyConnection,
    table_name: str,
    min_rows: int = 1,
    max_rows: Optional[int] = None,
) -> bool:
    """PASS if table row count is within [min_rows, max_rows]."""
    result = conn.sql(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    count = result[0] if result else 0
    if count < min_rows:
        return False
    if max_rows is not None and count > max_rows:
        return False
    return True


# SECTION 3: PRO VERSION — Thresholds + Debugging samples
#   Not every pipeline needs 100% perfection.
#   Add a pass_threshold and return bad rows for debugging.

def run_check_with_details(
    conn: DuckDBPyConnection,
    table_name: str,
    check_sql: str,          # SQL that selects FAILING rows
    count_sql: str,          # SQL that counts total rows
    pass_threshold: float = 1.0,
    sample_size: int = 5,
) -> dict[str, Any]:
    """
    Generic wrapper that:
    - Samples failing rows for debugging
    - Calculates fail rate
    - Applies a pass threshold
    Returns a result dict.
    """
    # Get a sample of failing rows
    sample_query = f"{check_sql} USING SAMPLE {sample_size}"
    violations = conn.sql(sample_query).fetchall()

    # Get column names for pretty output
    col_names = [desc[0] for desc in conn.sql(check_sql + " LIMIT 0").description]

    # Count total rows
    total_result = conn.sql(count_sql).fetchone()
    total = total_result[0] if total_result else 0

    # Count failures (subquery approach so we don't double-fetch)
    fail_count_sql = f"SELECT COUNT(*) FROM ({check_sql})"
    fail_count_result = conn.sql(fail_count_sql).fetchone()
    fail_count = fail_count_result[0] if fail_count_result else 0

    fail_rate = round(fail_count / total, 4) if total > 0 else 0.0
    pass_rate  = 1 - fail_rate
    passed     = pass_rate >= pass_threshold

    return {
        "passed":      passed,
        "pass_rate":   round(pass_rate * 100, 1),
        "fail_rate":   round(fail_rate * 100, 1),
        "total_rows":  total,
        "fail_count":  fail_count,
        "columns":     col_names,
        "violations":  violations,
        "threshold":   round(pass_threshold * 100, 1),
    }


# SECTION 4: MINI FRAMEWORK — Run all checks & produce a report

class DataQualityCheck:
    def __init__(self, name: str, passed: bool, details: str = ""):
        self.name    = name
        self.passed  = passed
        self.details = details

    def __repr__(self):
        icon = "PASS" if self.passed else "FAIL"
        line = f"  {icon}  {self.name}"
        if self.details:
            line += f"\n         └─ {self.details}"
        return line


def print_report(checks: list[DataQualityCheck], table_name: str) -> None:
    total  = len(checks)
    passed = sum(1 for c in checks if c.passed)
    failed = total - passed
    bar    = "=" * 56

    print(f"\n{bar}")
    print(f"  DATA QUALITY REPORT — {table_name.upper()}")
    print(bar)
    for check in checks:
        print(check)
    print(bar)
    print(f"  SUMMARY: {passed}/{total} checks passed  |  {failed} FAILED")
    print(bar)


# DEMO: Run everything live

def main():
    print("\n" + "="*56)
    print("  DATA QUALITY CHECKS IN PYTHON — ZERO THIRD-PARTY TOOLS")
    print("="*56 + "\n")

    conn = duckdb.connect()
    setup_demo_database(conn)

    checks: list[DataQualityCheck] = []

    # ── BASIC CHECKS ────────────────────────────────────────

    print("── RUNNING BASIC CHECKS ────────────────────────────")

    # 1. Valid status values
    allowed = ["completed", "pending", "shipped", "refunded"]
    result  = check_values_in_set(conn, "orders", "status", allowed)
    checks.append(DataQualityCheck(
        "status values in allowed set",
        result,
        f"Allowed: {allowed}"
    ))

    # 2. No nulls in critical column
    result = check_not_null(conn, "orders", "status")
    checks.append(DataQualityCheck(
        "status column has no NULLs",
        result,
    ))

    # 3. Unique order IDs
    result = check_unique(conn, "orders", "order_id")
    checks.append(DataQualityCheck(
        "order_id is unique",
        result,
    ))

    # 4. Amount is positive
    result = check_value_range(conn, "orders", "amount", min_val=0)
    checks.append(DataQualityCheck(
        "amount >= 0 (no negative orders)",
        result,
    ))

    # 5. Email matches basic pattern
    result = check_regex_pattern(conn, "orders", "email", r"^[^@]+@[^@]+\.[^@]+$")
    checks.append(DataQualityCheck(
        "email matches basic pattern",
        result,
    ))

    # 6. Row count sanity check
    result = check_row_count(conn, "orders", min_rows=5, max_rows=10_000)
    checks.append(DataQualityCheck(
        "order count between 5 and 10,000",
        result,
    ))

    print_report(checks, "orders")

    # ── VERSION WITH THRESHOLDS ──────────────────────────

    print("\n\n── THRESHOLD-BASED CHECKS WITH DEBUG SAMPLES ─")

    check_sql = """
        SELECT *
        FROM   orders
        WHERE  status NOT IN ('completed', 'pending', 'shipped', 'refunded')
           OR  status IS NULL
    """
    count_sql = "SELECT COUNT(*) FROM orders"

    result = run_check_with_details(
        conn,
        table_name="orders",
        check_sql=check_sql,
        count_sql=count_sql,
        pass_threshold=0.80,   # Allow up to 20% failures
        sample_size=5,
    )

    print(f"\n  Check: status values in allowed set")
    print(f"  Threshold : {result['threshold']}% must pass")
    print(f"  Pass Rate : {result['pass_rate']}%")
    print(f"  Fail Count: {result['fail_count']} / {result['total_rows']} rows")
    print(f"  Result    : {'PASSED' if result['passed'] else 'FAILED'}")

    if result["violations"]:
        print(f"\n  Sample failing rows (columns: {result['columns']}):")
        for row in result["violations"]:
            print(f"    → {row}")

    print("\n  (With pass_threshold=0.80 and only 20% bad rows → PASSES!)")

    # ── SHOW THE DUPLICATE ───────────────────────────────────

    print("\n\n── INVESTIGATING THE DUPLICATE order_id ────────────────")
    dupes = conn.sql("""
        SELECT order_id, COUNT(*) AS occurrences
        FROM   orders
        GROUP BY order_id
        HAVING COUNT(*) > 1
    """).fetchall()
    for row in dupes:
        print(f"  order_id {row[0]} appears {row[1]} times ← DUPLICATE!")

    print("\n🎬 That's all folks! Checks done. No Great Expectations needed.")


if __name__ == "__main__":
    main()
