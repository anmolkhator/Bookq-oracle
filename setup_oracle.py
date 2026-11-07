"""Create the BookQ tables, PL/SQL package and trigger in Oracle, then load the sample data.

    python setup_oracle.py            create what is missing and load books.csv
    python setup_oracle.py --reset    drop the BookQ tables first (all data is lost)
"""
import os
import sys

import oracledb

import oracle_db

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = ["history", "holds", "loans", "users", "books"]


def statements(path):
    chunks, cur = [], []
    for line in open(path, encoding="utf-8"):
        if line.strip() == "/":
            chunks.append("\n".join(cur).strip())
            cur = []
        else:
            cur.append(line.rstrip())
    body = []
    for c in chunks:
        lines = [l for l in c.splitlines()]
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
            lines.pop(0)
        if lines:
            body.append("\n".join(lines))
    return body


def main():
    print(f"Connecting to {oracle_db.DSN} as {oracle_db.USER} ...")
    con = oracledb.connect(user=oracle_db.USER, password=oracle_db.PASSWORD, dsn=oracle_db.DSN)
    cur = con.cursor()
    if "--reset" in sys.argv:
        for t in TABLES:
            try:
                cur.execute(f"DROP TABLE {t} CASCADE CONSTRAINTS PURGE")
                print(f"dropped {t}")
            except oracledb.DatabaseError as e:
                if "ORA-00942" not in str(e):
                    raise
    for sql in statements(os.path.join(HERE, "oracle_setup.sql")):
        label = " ".join(sql.split()[:4])
        try:
            cur.execute(sql)
            print("ok      ", label)
        except oracledb.DatabaseError as e:
            if "ORA-00955" in str(e):                 # name is already used by an existing object
                print("exists  ", label)
            else:
                raise
    cur.execute("SELECT name, type, line, text FROM user_errors ORDER BY name, sequence")
    errs = cur.fetchall()
    if errs:
        print("\nPL/SQL compile errors:")
        for n, t, line, text in errs:
            print(f"  {t} {n} line {line}: {text}")
        sys.exit(1)
    cur.execute("SELECT COUNT(*) FROM books")
    if cur.fetchone()[0] == 0:
        print(f"loaded {oracle_db.seed()} books and the demo accounts")
    else:
        print("books table already has data, nothing loaded")
    con.close()
    print("\nDone. Start the site with:  streamlit run bookq.py")


if __name__ == "__main__":
    main()
