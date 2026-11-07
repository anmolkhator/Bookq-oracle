# BookQ with Oracle Database

BookQ (Streamlit) now stores everything in **Oracle Database**.
Borrow, return, renew and reserve are **PL/SQL procedures** in the package `pkg_library`,
and a **trigger** copies every returned loan into the history table.

| File | What it does |
|---|---|
| `bookq.py` | The website (Streamlit) |
| `oracle_db.py` | Connection pool, `run()` for SQL, `call()` for PL/SQL |
| `oracle_setup.sql` | Tables, indexes, package `pkg_library`, trigger `trg_loans_to_history` |
| `setup_oracle.py` | Runs `oracle_setup.sql` and loads `books.csv` + demo accounts |
| `books.csv` | The book list (1,035 books, including the Oracle & PL/SQL shelf) |

## 1. Start an Oracle database

**Docker (works on Apple Silicon Macs).** Install Docker Desktop, then:

```bash
docker run -d --name oracle-free -p 1521:1521 \
  -e ORACLE_PASSWORD=admin123 \
  -e APP_USER=bookq -e APP_USER_PASSWORD=bookq123 \
  -v oracle-data:/opt/oracle/oradata \
  gvenzl/oracle-free:slim
```

Wait a few minutes until `docker logs oracle-free` shows "DATABASE IS READY TO USE".
Next time, start it with `docker start oracle-free`.

Other options: Oracle XE on Windows/Linux (Intel), or Oracle Cloud Free Tier.
For those, set the variables below to your own user, password and service name.

## 2. Install and set up

```bash
cd oraclebookq
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup_oracle.py          # creates tables, package, trigger and loads the books
```

`python setup_oracle.py --reset` drops the BookQ tables and starts again.

## 3. Run

```bash
streamlit run bookq.py
```

Demo accounts: `asha`, `rohan`, `priya`, all with password `bookq123`.

## Connection settings

Defaults are `bookq` / `bookq123` / `localhost:1521/FREEPDB1`. Change them with environment variables:

```bash
export ORACLE_USER=bookq
export ORACLE_PASSWORD=bookq123
export ORACLE_DSN=localhost:1521/FREEPDB1     # host:port/service_name
```

For Oracle XE the service name is usually `XEPDB1`.

## Where Oracle and PL/SQL are used

| In the site | In Oracle |
|---|---|
| Catalog, search, shelves, My account | SQL queries on `books`, `loans`, `holds`, `history` |
| Borrow button | `pkg_library.borrow_book` (limit of 5, copy check, row lock) |
| Return button | `pkg_library.return_book` + trigger `trg_loans_to_history` |
| Renew button | `pkg_library.renew_loan` (once only, not if reserved) |
| Reserve / Cancel | `pkg_library.reserve_book`, `pkg_library.cancel_hold` |

Errors raised with `RAISE_APPLICATION_ERROR` (-20001 to -20006) appear as messages on the site.

## Try the PL/SQL by hand (SQL Developer or SQL*Plus)

```sql
SET SERVEROUTPUT ON
DECLARE
  v_due DATE;
BEGIN
  pkg_library.borrow_book(20, 'priya', v_due);
  DBMS_OUTPUT.PUT_LINE('Due: ' || TO_CHAR(v_due, 'YYYY-MM-DD'));
END;
/
SELECT * FROM loans WHERE username = 'priya';
```
