"""Oracle database layer for BookQ.

Connection settings come from environment variables (defaults match the Docker
command in README_ORACLE.md):
    ORACLE_USER      default: bookq
    ORACLE_PASSWORD  default: bookq123
    ORACLE_DSN       default: localhost:1521/FREEPDB1
"""
import csv
import hashlib
import os
import re
import secrets
from datetime import datetime

import oracledb

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(HERE, "books.csv")

USER = os.environ.get("ORACLE_USER", "bookq")
PASSWORD = os.environ.get("ORACLE_PASSWORD", "bookq123")
DSN = os.environ.get("ORACLE_DSN", "localhost:1521/FREEPDB1")

_pool = None


class BookqError(Exception):
    """A rule enforced by the PL/SQL package (for example: limit reached)."""


def pool():
    """One shared connection pool for the whole app (python-oracledb thin mode)."""
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(user=USER, password=PASSWORD, dsn=DSN, min=1, max=5, increment=1)
    return _pool


def _binds(sql):
    """The app writes ? placeholders; Oracle wants :1, :2, ..."""
    n = 0

    def nxt(_):
        nonlocal n
        n += 1
        return f":{n}"
    return re.sub(r"\?", nxt, sql)


def _py(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")            # the app shows and parses ISO dates
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def run(sql, args=()):
    """Run one SQL statement and return rows as dicts with lower-case keys."""
    with pool().acquire() as con:
        with con.cursor() as cur:
            cur.execute(_binds(sql), list(args))
            rows = []
            if cur.description:
                cols = [d[0].lower() for d in cur.description]
                rows = [{c: _py(v) for c, v in zip(cols, r)} for r in cur.fetchall()]
            con.commit()
            return rows


def call(proc, *args, out_date=False):
    """Call a PL/SQL procedure. With out_date=True the last parameter is an OUT DATE, returned as a datetime."""
    with pool().acquire() as con:
        with con.cursor() as cur:
            params = list(args)
            out = None
            if out_date:
                out = cur.var(oracledb.DB_TYPE_DATE)
                params.append(out)
            try:
                cur.callproc(proc, params)
                con.commit()
            except oracledb.DatabaseError as e:
                con.rollback()
                err = e.args[0]
                msg = getattr(err, "message", str(err))
                m = re.search(r"ORA-200\d\d: (.*)", msg)     # our RAISE_APPLICATION_ERROR messages
                if m:
                    raise BookqError(m.group(1).strip()) from None
                raise
            return out.getvalue() if out is not None else None


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


def add_user(username, name, pw):
    salt, h = hash_pw(pw)
    run("INSERT INTO users(username,name,salt,pw) VALUES(?,?,?,?)", (username, name, salt, h))


def seed(csv_file=CSV_FILE):
    """Load books.csv and a few demo accounts, loans and history (only when the books table is empty)."""
    with open(csv_file, newline="", encoding="utf-8-sig") as f:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    data = [(r["title"], r.get("author") or None, int(r.get("year") or 0), r.get("category") or "Fiction",
             max(1, int(r.get("copies") or 1)), r.get("isbn") or None, r.get("description") or None, r.get("poster") or None)
            for r in rows if r.get("title")]
    with pool().acquire() as con:
        with con.cursor() as cur:
            cur.setinputsizes(400, 400, oracledb.DB_TYPE_NUMBER, 100, oracledb.DB_TYPE_NUMBER, 50, 2000, 300)
            cur.executemany("INSERT INTO books(title,author,year,cat,copies,isbn,descr,poster) VALUES(:1,:2,:3,:4,:5,:6,:7,:8)", data)
            for u, n in (("asha", "Asha Verma"), ("rohan", "Rohan Mehta"), ("priya", "Priya Kapoor")):
                salt, h = hash_pw("bookq123")                       # demo password
                cur.execute("INSERT INTO users(username,name,salt,pw) VALUES(:1,:2,:3,:4)", (u, n, salt, h))
            for bid, u, i, d, ren in [(5, "asha", -8, 6, 0), (7, "asha", -17, -3, 0), (6, "rohan", -5, 9, 0), (15, "priya", -12, 2, 1)]:
                cur.execute("INSERT INTO loans(book_id,username,issued,due,renewed) VALUES(:1,:2,TRUNC(SYSDATE)+:3,TRUNC(SYSDATE)+:4,:5)",
                            (bid, u, i, d, ren))
            cur.execute("INSERT INTO holds(book_id,username) VALUES(6,'asha')")
            for bid, u, i, r in [(1, "asha", -45, -32), (13, "asha", -30, -18), (9, "rohan", -20, -9)]:
                cur.execute("INSERT INTO history(book_id,username,issued,returned) VALUES(:1,:2,TRUNC(SYSDATE)+:3,TRUNC(SYSDATE)+:4)",
                            (bid, u, i, r))
        con.commit()
    return len(data)


def ensure_seeded():
    """Raises if the tables are missing (run setup_oracle.py first); seeds when the books table is empty."""
    if run("SELECT COUNT(*) c FROM books")[0]["c"] == 0 and os.path.exists(CSV_FILE):
        seed()
