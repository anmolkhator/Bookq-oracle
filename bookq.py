"""BookQ - library website written in Python (Streamlit + Oracle Database).

Setup:  see README_ORACLE.md  (start Oracle, then: python setup_oracle.py)
Run:    pip install -r requirements.txt
        streamlit run bookq.py

Data lives in Oracle. Borrow, return, renew and reserve are PL/SQL procedures
in the pkg_library package (oracle_setup.sql); oracle_db.py is the connection layer.

books.csv  the book list, loaded into Oracle by setup_oracle.py (or on first run if the table is empty).
posters/   put poster images here (see posters/README.txt). Empty until you add them.
"""
import base64
import csv
import hashlib
import html
import math
import os
import random
import re
import secrets
import urllib.parse
from datetime import date, timedelta

import streamlit as st

from oracle_db import BookqError, add_user, call, ensure_seeded, hash_pw, run

HERE = os.path.dirname(os.path.abspath(__file__))
POSTERS = os.path.join(HERE, "posters")
PER_PAGE, PER_ROW, MAX_LOANS, LOAN_DAYS = 12, 4, 5, 14
CATS = {"Fiction": "#1f5c5a", "Mystery": "#6b3f7a", "Science Fiction": "#2d5fa3", "History": "#9a6f14",
        "Science": "#2f7d4f", "Biography": "#b0533b", "Children": "#c28a1d", "Technology": "#475a66", "Oracle & PL/SQL": "#b3321f"}
SORTS = {"Title": "UPPER(title)", "Author": "UPPER(author)", "Newest first": "year DESC"}
BOOKS_SQL = ("SELECT b.*, b.copies - (SELECT COUNT(*) FROM loans l WHERE l.book_id = b.id) AS avail FROM books b")

# ------------------------------------------------------------------ page text
ABOUT = [("Your library, online", "BookQ is a community library catalog made for readers. Browse the whole collection from home, check which books are on the shelf right now, and plan your next visit before you leave the house. Everything from classic novels to practical guides is in one place."),
         ("Our books", "The shelves cover nine categories: fiction, mystery, science fiction, history, science, biography, books for children, technology, and a dedicated Oracle & PL/SQL shelf for database learners. Every book has a call number so you can find it quickly, and the catalog shows how many copies are available today.")]
ORACLE_PATH = [("1. Start with SQL", "Learn SELECT, joins, grouping and subqueries first. Oracle SQL is the base that PL/SQL builds on, so a few weeks of query practice pays off later."),
               ("2. Learn PL/SQL", "Move on to anonymous blocks, variables, IF and loops, cursors, exception handling, then stored procedures, functions, packages and triggers."),
               ("3. Go deeper", "Study how the database works: transactions, locking, indexes and the optimizer. Then tune your SQL and PL/SQL with real execution plans.")]
PLSQL_REF = [("Block structure", "Every PL/SQL program is a block: <code>DECLARE</code> (optional), <code>BEGIN</code> ... <code>EXCEPTION</code> (optional) ... <code>END;</code>. Blocks can be nested."),
             ("Cursors and loops", "Use <code>FOR rec IN (SELECT ...) LOOP</code> to read rows one by one. For large data sets, <code>BULK COLLECT</code> and <code>FORALL</code> are much faster."),
             ("Error handling", "Catch problems in the <code>EXCEPTION</code> section with handlers such as <code>NO_DATA_FOUND</code>, <code>TOO_MANY_ROWS</code> and <code>OTHERS</code>. Use <code>RAISE_APPLICATION_ERROR</code> for your own errors."),
             ("Stored code", "Procedures and functions live in the database. Group related ones into a <b>package</b> with a specification and a body, and use triggers to react to table changes.")]
STEPS = [("1. Search", "Find a book by title, author or category."), ("2. Borrow or reserve", "Take it for 14 days, or reserve it if all copies are out."),
         ("3. Return or renew", "Return it on time, or renew once from My account.")]
RULES = [("Issuing a book", "To issue a book, find it in the catalog, open its details and choose Borrow. You can have up to 5 books on loan at the same time, and each loan lasts 14 days. The due date shows up at once in My account."),
         ("Reserving a book", "If every copy of a title is out, choose Reserve. We hold the next returned copy for you, and the book appears as ready to borrow in My account as soon as it is back on the shelf."),
         ("Returning and renewing", "Return a book from My account or at the desk. Need more time? Renew once for another 14 days, unless another member has reserved the book. Overdue loans are marked in red so they are easy to spot.")]
TIPS = [("Choosing your next book", "Start with a category you already enjoy, then try one neighbouring shelf. If a title is out, reserve it and pick up something close in the meantime."),
        ("Building a reading habit", "A short, regular slot works better than a long, rare one. Twenty minutes before bed or on the commute adds up to a book in a few weeks."),
        ("Reading with children", "Read aloud together and let the child choose the book. Short picture books are ideal for bedtime, and a favourite is worth borrowing again.")]
EVENTS = [("Story hour", "A weekly morning of stories, songs and crafts for young listeners and their families."),
          ("Book club", "A monthly meeting where members share what they have read and vote on the next title."),
          ("Author talks", "Guest writers visit to read from their work and answer questions from the audience.")]
GOOD = [("For young readers", "The children section has picture books and read-aloud favourites. Parents and carers can borrow on behalf of a child and keep track of due dates from one account."),
        ("Your borrowing page", "My account shows everything you have issued: the books on loan, how many days are left, your reservations and the books you have returned."),
        ("Visiting us", "The library is open Monday to Friday from 9 am to 7 pm and on Saturday from 10 am to 4 pm. It is closed on Sunday.")]
FAQ = [("Where are the Oracle and PL/SQL books?", "They have their own category, Oracle & PL/SQL. Choose it from the Categories menu or the sidebar, or search for a word such as Oracle, PL/SQL or SQL."),
       ("How many books can I borrow at once?", "You can have up to 5 books on loan at the same time."),
       ("How long can I keep a book?", "Each loan lasts 14 days. The due date appears in My account as soon as you borrow."),
       ("Can I renew a book?", "Yes, once, for another 14 days, unless another member has reserved it."),
       ("What if every copy is out?", "Choose Reserve on the book. We hold the next returned copy for you and it shows as Ready to borrow in My account."),
       ("Do I need an account to browse?", "No. Anyone can search the catalog. You need an account to borrow, reserve and keep track of your books."),
       ("What happens if a book is overdue?", "It is marked in red in My account, with the number of days overdue. Please return it as soon as you can."),
       ("Can I see the books I returned earlier?", "Yes. Your returned books, with the dates you issued and returned them, are listed in My account.")]

ICON = ('<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<circle cx="9" cy="10" r="1.8"/><path d="M3 17l5-4 4 3 3-2 6 4"/></svg>')
LOGO = ('<svg viewBox="0 0 48 48" width="58" height="58"><circle cx="22" cy="22" r="17" fill="none" stroke="#c9a24a" stroke-width="4"/>'
        '<path d="M12 17c4-2 7-1.5 10 1v12c-3-2.5-6-3-10-1z" fill="#fff"/><path d="M32 17c-4-2-7-1.5-10 1v12c3-2.5 6-3 10-1z" fill="#d9e3ee"/>'
        '<path d="M29 29l9 11" stroke="#c9a24a" stroke-width="5" stroke-linecap="round"/></svg>')


# ------------------------------------------------------------- background art
def data_url(svg):
    return 'url("data:image/svg+xml,' + urllib.parse.quote(svg, safe="") + '")'


def backgrounds():
    ns = "xmlns='http://www.w3.org/2000/svg'"
    pal = ["#c9a24a", "#1f5c5a", "#6b3f7a", "#2d5fa3", "#b0533b", "#2f7d4f", "#e9e4d8", "#9a6f14"]
    r, x, o = random.Random(7), 0, []
    while x < 900:                                   # bookshelf strip
        w, h = r.randint(14, 30), r.randint(48, 108)
        o.append(f"<rect x='{x}' y='{116 - h}' width='{w - 2}' height='{h}' rx='2' fill='{r.choice(pal)}' opacity='.6'/>"
                 f"<rect x='{x + 2}' y='{126 - h}' width='{w - 6}' height='3' fill='#fff' opacity='.35'/>")
        x += w
    o.append("<rect y='116' width='900' height='4' fill='#c9a24a' opacity='.85'/>")
    shelf = data_url(f"<svg {ns} width='900' height='120' viewBox='0 0 900 120'>{''.join(o)}</svg>")
    book = ("<path d='M0 8c9-4 16-3 22 2v22c-6-5-13-6-22-2zM44 8c-9-4-16-3-22 2v22c6-5 13-6 22-2z' fill='none' "
            "stroke='#7a8a94' stroke-width='1.6' stroke-linejoin='round'/>")
    page = data_url(f"<svg {ns} width='180' height='180' viewBox='0 0 180 180'><g opacity='.16'><g transform='translate(18 20) rotate(-8)'>{book}</g>"
                    f"<g transform='translate(112 96) rotate(9)'>{book}</g><circle cx='96' cy='30' r='2' fill='#7a8a94'/>"
                    "<circle cx='30' cy='120' r='2' fill='#7a8a94'/><circle cx='150' cy='160' r='2' fill='#7a8a94'/></g></svg>")
    dia = data_url(f"<svg {ns} width='44' height='44' viewBox='0 0 44 44'><path d='M22 2L42 22L22 42L2 22Z' fill='none' stroke='#fff' stroke-width='1' opacity='.09'/></svg>")

    def stack(flip):
        rr, y, out = random.Random(11), 150, []
        for _ in range(6):
            w, h, xx = rr.randint(86, 124), rr.randint(14, 19), 10 + rr.randint(0, 24)
            y -= h
            out.append(f"<rect x='{xx}' y='{y}' width='{w}' height='{h - 2}' rx='3' fill='{rr.choice(pal)}' opacity='.5'/>"
                       f"<rect x='{xx + 8}' y='{y + 4}' width='{w - 16}' height='2' fill='#fff' opacity='.4'/>")
        g = "<g transform='translate(160 0) scale(-1 1)'>" if flip else "<g>"
        return data_url(f"<svg {ns} width='160' height='160' viewBox='0 0 160 160'>{g}{''.join(out)}</g></svg>")
    return {"__SHELF__": shelf, "__PAGE__": page, "__DIA__": dia, "__STACKR__": stack(False), "__STACKL__": stack(True)}



CSS = """
.stApp{background-image:__PAGE__}
.block-container{max-width:1100px;padding-top:1rem}

.top{position:relative;background-color:#12304f;background-image:__DIA__;color:#fff;text-align:center;padding:16px 90px;border-bottom:4px solid #c9a24a;border-radius:6px;margin-bottom:12px;min-height:62px}
.top .logo{position:absolute;left:16px;top:50%;transform:translateY(-50%);line-height:0}
.top h1{color:#fff;font:700 1.8rem Georgia,serif;margin:0;padding:0}
.top p{margin:4px 0 0;color:#c5d3e0;font:italic 1.05rem Georgia,serif}

div[role=radiogroup]{justify-content:center;gap:.5rem;flex-wrap:wrap}

.hero{background-color:#12304f;background-image:__SHELF__,linear-gradient(135deg,#12304f,#14416b);background-repeat:repeat-x,no-repeat;background-position:bottom,center;background-size:auto 118px,cover;color:#fff;border-radius:8px;padding:52px 24px 150px;text-align:center}
.hero h2{color:#fff;font:700 2.2rem Georgia,serif;margin:0;padding:0}
.hero p{margin:10px auto 0;max-width:52ch;color:#c5d3e0}

.slot{aspect-ratio:5/7;border:2px dashed rgba(127,127,127,.5);border-left:6px solid var(--c);border-radius:4px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;color:rgba(127,127,127,.95);font-size:.8rem;background:repeating-linear-gradient(45deg,transparent,transparent 8px,rgba(127,127,127,.09) 8px,rgba(127,127,127,.09) 16px);margin-bottom:6px}
.slot.mini{width:56px;font-size:0}
.slot.mini svg{width:22px;height:22px}

.ttl{font-weight:700;line-height:1.3;height:2.6em;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.sub{opacity:.7;font-size:.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:2px 0 6px}
.stat{font-weight:600;font-size:.9rem;margin-bottom:6px}
.stat.ok{color:#2e9e5b}
.stat.no{color:#d64545}

[data-testid="stImage"] img{aspect-ratio:5/7;object-fit:contain;width:100%;background:#f4f1e9}

.sec{margin:28px 0 12px}
.info{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.blk{border:1px solid rgba(127,127,127,.3);background:rgba(127,127,127,.08);border-radius:6px;padding:18px}
.blk h3{margin:0 0 6px;font-size:1.05rem;padding:0}
.blk p{margin:0;opacity:.82;line-height:1.65}

.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0 4px}
.strip div{border:1px solid rgba(127,127,127,.3);background:rgba(127,127,127,.08);border-radius:6px;padding:14px;text-align:center}
.strip b{display:block;font:700 1.3rem Georgia,serif;color:#c9a24a}
.strip span{opacity:.8;font-size:.88rem}

.cta{background-color:#12304f;background-image:__STACKL__,__STACKR__,linear-gradient(135deg,#12304f,#14416b);background-repeat:no-repeat;background-position:left 28px bottom,right 28px bottom,center;background-size:auto 150px,auto 150px,cover;color:#fff;border-radius:8px;padding:44px 24px 48px;text-align:center;margin:32px 0 8px}
.cta h2{color:#fff;font:700 1.6rem Georgia,serif;margin:0;padding:0}
.cta p{margin:8px auto 0;color:#c5d3e0;max-width:50ch}

@media(max-width:760px){
    .cta{background-image:linear-gradient(135deg,#12304f,#14416b)}
}

@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
@keyframes drift{from{transform:translate(0,0) scale(1)}to{transform:translate(40px,30px) scale(1.15)}}
@keyframes sheen{to{transform:translateX(100%)}}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}

.block-container{animation:rise .6s ease both}
.top h1,.top p{animation:rise .8s ease both}
.top p{animation-delay:.15s}
.top .logo svg{transition:transform .6s cubic-bezier(.3,1.4,.5,1)}
.top .logo:hover svg{transform:rotate(-10deg) scale(1.1)}

.hero{position:relative;overflow:hidden}
.hero::before,.hero::after{content:"";position:absolute;border-radius:50%;pointer-events:none;animation:drift 14s ease-in-out infinite alternate}
.hero::before{width:300px;height:300px;top:-110px;left:-70px;background:radial-gradient(circle,rgba(201,162,74,.35),transparent 70%)}
.hero::after{width:340px;height:340px;right:-90px;top:-40px;background:radial-gradient(circle,rgba(91,192,190,.28),transparent 70%);animation-duration:18s}
.hero>*{position:relative;z-index:1}
.hero h2{animation:rise .8s ease both}
.hero p{animation:rise .8s .15s ease both}

.blk,.strip div{transition:transform .25s,box-shadow .25s,border-color .25s}
.blk:hover,.strip div:hover{transform:translateY(-4px);box-shadow:0 12px 24px rgba(0,0,0,.18);border-color:#c9a24a}

[data-testid="stVerticalBlockBorderWrapper"]:has(.ttl){transition:transform .25s,box-shadow .25s,border-color .25s}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ttl):hover{transform:translateY(-6px);box-shadow:0 16px 30px rgba(0,0,0,.22);border-color:#c9a24a}

.slot{position:relative;overflow:hidden}
.slot::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.35) 50%,transparent 70%);transform:translateX(-100%);pointer-events:none}
[data-testid="stVerticalBlockBorderWrapper"]:hover .slot::after{animation:sheen .9s ease}

.stButton>button{transition:transform .15s,box-shadow .2s}
.stButton>button:hover{transform:translateY(-2px);box-shadow:0 8px 18px rgba(0,0,0,.2)}

div[role=radiogroup] label{transition:transform .15s}
div[role=radiogroup] label:hover{transform:translateY(-2px)}

@supports (animation-timeline:view()){
    .sec,.blk,.strip div,.cta,[data-testid="stVerticalBlockBorderWrapper"]:has(.ttl){animation:rise linear backwards;animation-timeline:view();animation-range:entry 0% entry 35%}
}
@supports (animation-timeline:scroll()){
    .stApp::before{content:"";position:fixed;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#c9a24a,#f4d58d);transform-origin:0 50%;z-index:999;animation:grow linear both;animation-timeline:scroll(root)}
}
@media (prefers-reduced-motion:reduce){
    *,*::before,*::after{animation:none!important;transition:none!important}
    .slide:first-child{opacity:1!important}
}

/* RESPONSIVE BOOK SHELVES */

[class*="st-key-bookq-shelf-"]{
    width:100% !important;
    min-width:0 !important;
}

[class*="st-key-bookq-shelf-"] [data-testid="stHorizontalBlock"]{
    display:flex !important;
    flex-wrap:wrap !important;
    gap:12px !important;
    align-items:stretch !important;
}

[class*="st-key-bookq-shelf-"] [data-testid="column"]{
    box-sizing:border-box !important;
    min-width:0 !important;
    flex:0 0 calc(16.6667% - 10px) !important;
    width:calc(16.6667% - 10px) !important;
    max-width:calc(16.6667% - 10px) !important;
}

[data-testid="stVerticalBlockBorderWrapper"]{
    min-width:0 !important;
    max-width:100% !important;
}

[data-testid="stExpander"]{
    width:100% !important;
    min-width:0 !important;
}

.stButton,
.stButton>button{
    width:100% !important;
    min-width:0 !important;
    box-sizing:border-box !important;
}

.stButton>button{
    white-space:normal !important;
    word-break:normal !important;
    overflow-wrap:break-word !important;
    line-height:1.3 !important;
    padding:8px 6px !important;
    height:auto !important;
    min-height:42px !important;
    font-size:clamp(12px,1.2vw,15px) !important;
}

/* MEDIUM SCREENS: 3 BOOKS PER ROW */

@media(max-width:900px){
    .block-container{
        padding-left:1rem;
        padding-right:1rem;
    }

    [class*="st-key-bookq-shelf-"] [data-testid="column"]{
        flex:0 0 calc(33.3333% - 10px) !important;
        width:calc(33.3333% - 10px) !important;
        max-width:calc(33.3333% - 10px) !important;
    }

    .top{padding:16px 70px}
    .hero{padding:40px 18px 125px}
}

/* SMALL SCREENS: 2 BOOKS PER ROW */

@media(max-width:520px){
    [class*="st-key-bookq-shelf-"] [data-testid="column"]{
        flex:0 0 calc(50% - 6px) !important;
        width:calc(50% - 6px) !important;
        max-width:calc(50% - 6px) !important;
    }

    .block-container{
        padding-left:.7rem !important;
        padding-right:.7rem !important;
    }

    .top{padding:14px 12px 14px 58px}
    .top h1{font-size:1.4rem}
    .top p{font-size:.9rem}
    .hero{padding:30px 14px 105px}
    .hero h2{font-size:1.6rem}
    .stButton>button{font-size:13px !important}
}

/* BOOK WALL */

.big{position:relative;width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;border-left:8px solid var(--c);background:repeating-linear-gradient(45deg,transparent,transparent 12px,rgba(127,127,127,.09) 12px,rgba(127,127,127,.09) 24px),linear-gradient(135deg,rgba(127,127,127,.1),rgba(127,127,127,.2));color:rgba(127,127,127,.95);text-align:center}
.big img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#12304f}
.big .cap{position:absolute;left:0;right:0;bottom:0;padding:20px 24px;background:linear-gradient(transparent,rgba(10,24,40,.78));color:#fff;text-align:left}
.big .cap b{display:block;font:700 1.5rem Georgia,serif;color:#fff}
.big .cap span{opacity:.9}

.slider{position:relative;aspect-ratio:16/6;border-radius:12px;overflow:hidden;margin:18px 0;border:1px solid rgba(127,127,127,.3);box-shadow:0 10px 30px rgba(0,0,0,.15)}
.slide{position:absolute;inset:0;opacity:0;animation:cycle 20s infinite}
.slide:nth-child(2){animation-delay:5s}
.slide:nth-child(3){animation-delay:10s}
.slide:nth-child(4){animation-delay:15s}
@keyframes cycle{0%{opacity:0}3%{opacity:1}25%{opacity:1}28%{opacity:0}100%{opacity:0}}

.dots{position:absolute;top:14px;right:18px;display:flex;gap:8px;z-index:2}
.dots i{width:10px;height:10px;border-radius:50%;background:rgba(127,127,127,.55);animation:dot 20s infinite}
.dots i:nth-child(2){animation-delay:5s}
.dots i:nth-child(3){animation-delay:10s}
.dots i:nth-child(4){animation-delay:15s}
@keyframes dot{0%{background:#c9a24a;transform:scale(1.4)}25%{background:#c9a24a;transform:scale(1.4)}28%{background:rgba(127,127,127,.55);transform:none}100%{background:rgba(127,127,127,.55);transform:none}}

.wall{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}
.wall .big{aspect-ratio:2/3;height:auto;border-radius:12px;overflow:hidden;transition:transform .3s,box-shadow .3s}
.wall .big:hover{transform:translateY(-8px);box-shadow:0 22px 40px rgba(0,0,0,.28)}

.sbhead{display:flex;align-items:center;gap:10px;font:700 1.4rem Georgia,serif}
.sbhead svg{width:40px;height:40px}

@media(max-width:760px){
    .slider{aspect-ratio:16/10}
}

.foot{background-color:#12304f;background-image:__DIA__;color:#c5d3e0;margin-top:2.5rem;padding:1.5rem;border-top:4px solid #c9a24a;border-radius:6px}
.foot .g{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.5rem}
.foot h3{color:#fff;font-size:1rem;margin:0 0 .4rem;padding:0}
.foot p{margin:.1rem 0;font-size:.9rem}
.foot .b{border-top:1px solid rgba(255,255,255,.2);margin-top:1rem;padding-top:.7rem;font-size:.8rem}
"""



# -------------------------------------------------------------------- database
# All SQL runs in Oracle through oracle_db.py (run = one SQL statement, call = a PL/SQL procedure).
@st.cache_resource
def _ready():
    ensure_seeded()
    return True


def init_db():
    try:
        _ready()
    except Exception as e:
        st.error("BookQ cannot use the Oracle database yet. Check that Oracle is running and that you ran "
                 "`python setup_oracle.py` once (see README_ORACLE.md).")
        st.code(str(e))
        st.stop()


def iso(days):
    return (date.today() + timedelta(days)).isoformat()


def get_book(bid):
    return run(BOOKS_SQL + " WHERE b.id=?", (bid,))[0]


def pick(where="", args=(), skip=0, n=6):
    return run(f"SELECT * FROM ({BOOKS_SQL}){where} ORDER BY id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", tuple(args) + (skip, n))


def categories():
    return [r["cat"] for r in run("SELECT DISTINCT cat FROM books ORDER BY cat")]


# --------------------------------------------------------------------- session
def me():
    return st.session_state.get("user")


def first_name():
    row = run("SELECT name FROM users WHERE username=?", (me(),)) if me() else []
    return row[0]["name"].split()[0] if row else ""


def need_login():
    if me():
        return False
    st.session_state.nav, st.session_state.auth_msg = "auth", "Please sign in to borrow, reserve or manage books."
    return True


def login(u):
    s = st.session_state
    s.user, s.returning, s.auth_mode, s.nav, s.auth_err, s.auth_msg = u, True, "in", "account", "", ""
    s.flash = f"Welcome, {first_name()}"


def do_signup():
    s = st.session_state
    name, u, p = s.su_name.strip(), s.su_user.strip().lower(), s.su_pass
    if not name or not re.fullmatch(r"[a-z0-9_]{3,20}", u):
        s.auth_err = "Enter your name and a username of 3 to 20 lowercase letters, numbers or underscores."
    elif len(p) < 6:
        s.auth_err = "Use a password of at least 6 characters."
    elif run("SELECT 1 FROM users WHERE username=?", (u,)):
        s.auth_err = "That username is already taken."
    else:
        add_user(u, name, p)
        login(u)


def do_signin():
    s = st.session_state
    u = s.si_user.strip().lower()
    row = run("SELECT * FROM users WHERE username=?", (u,))
    if row and secrets.compare_digest(hash_pw(s.si_pass, row[0]["salt"])[1], row[0]["pw"]):
        login(u)
    else:
        s.auth_err = "Username or password is not correct."


def nav_changed():
    s = st.session_state
    if s.nav == "auth" and me():                      # the last tab is Sign out when signed in
        s.user, s.returning, s.auth_mode, s.nav, s.flash = None, True, "in", "home", "Signed out"


def nav_label(key):
    if key == "auth":
        return f"Sign out ({first_name()})" if me() else ("Sign in" if st.session_state.get("returning") else "Create account")
    return {"home": "Home", "catalog": "Catalog", "account": "My account"}[key]


def go(nav, cat=None, text=""):
    s = st.session_state
    s.nav, s.q, s.fc, s.pg = nav, text, cat or "All categories", 0


def set_mode(m):
    st.session_state.auth_mode, st.session_state.auth_err = m, ""


# --------------------------------------------------------------------- actions
def borrow(bid):
    if need_login():
        return
    try:
        due = call("pkg_library.borrow_book", bid, me(), out_date=True)    # PL/SQL: checks limit and copies
        st.toast(f"Borrowed. Due {due:%Y-%m-%d}")
    except BookqError as e:
        st.toast(str(e))


def reserve(bid):
    if not need_login():
        call("pkg_library.reserve_book", bid, me())
        st.toast("Reserved. We will hold the next copy for you")


def unhold(bid):
    if not need_login():
        call("pkg_library.cancel_hold", bid, me())
        st.toast("Reservation cancelled")


def give_back(lid):
    if need_login():
        return
    try:
        call("pkg_library.return_book", lid, me())      # a trigger copies the loan into history
        st.toast("Book returned")
    except BookqError as e:
        st.toast(str(e))


def renew(lid):
    if need_login():
        return
    try:
        due = call("pkg_library.renew_loan", lid, me(), out_date=True)
        st.toast(f"Renewed. New due date {due:%Y-%m-%d}")
    except BookqError as e:
        st.toast(str(e))


# -------------------------------------------------------------------- widgets
def poster_file(b):
    names = ([b["poster"]] if b["poster"] else []) + [f"{b['id']}.{e}" for e in ("jpg", "jpeg", "png", "webp")]
    for n in names:
        p = os.path.join(POSTERS, n)
        if os.path.isfile(p):
            return p
    return None


def show_poster(b, mini=False):
    p = poster_file(b)
    if p:
        if mini:
            st.image(p, width=60)
        else:
            st.image(p)
    else:
        color = CATS.get(b["cat"], "#14416b")
        st.markdown(f'<div class="slot{" mini" if mini else ""}" style="--c:{color}">{ICON}<span>Poster image</span></div>', unsafe_allow_html=True)


def call_no(b):
    return f"{b['cat'][:3].upper()} {b['author'].split()[-1][:3].upper()} {b['year']}"


def card(b, where):
    """One book in a bordered container: poster space, title, status and a Details section."""
    k, bid = where, b["id"]
    with st.container(border=True):
        show_poster(b)
        status = (f'<div class="stat ok">{b["avail"]} of {b["copies"]} available</div>' if b["avail"] > 0
                  else '<div class="stat no">All on loan</div>')
        st.markdown(f'<div class="ttl" title="{html.escape(b["title"])}">{html.escape(b["title"])}</div>'
                    f'<div class="sub">{html.escape(b["author"])}, {b["year"]} · {html.escape(b["cat"])}</div>{status}', unsafe_allow_html=True)
        with st.expander("Details"):
            mine = run("SELECT id FROM loans WHERE book_id=? AND username=?", (bid, me())) if me() else []
            held = run("SELECT 1 FROM holds WHERE book_id=? AND username=?", (bid, me())) if me() else []
            if mine:
                st.button("Return this book", key=f"{k}-r{bid}", on_click=give_back, args=(mine[0]["id"],), use_container_width=True)
            elif b["avail"] > 0:
                st.button(f"Borrow for {LOAN_DAYS} days", key=f"{k}-b{bid}", on_click=borrow, args=(bid,), use_container_width=True)
            elif held:
                st.button("Cancel reservation", key=f"{k}-u{bid}", on_click=unhold, args=(bid,), use_container_width=True)
            else:
                st.button("Reserve", key=f"{k}-h{bid}", on_click=reserve, args=(bid,), use_container_width=True)


def shelf(title, rows, where, cat=None):
    st.markdown(f'<h2 class="sec">{title}</h2>', unsafe_allow_html=True)

    with st.container(key=f"bookq-shelf-{where}"):
        per_row = 6

        for i in range(0, len(rows), per_row):
            cols = st.columns(per_row)

            for col, b in zip(cols, rows[i:i + per_row]):
                with col:
                    card(b, where)

    if cat:
        st.button(
            f"See all {cat if 'SQL' in cat else cat.lower()} books",
            key=f"all-{where}",
            on_click=go,
            args=("catalog", cat)
        )


def blocks(title, items):
    cells = "".join(f'<div class="blk"><h3>{h}</h3><p>{p}</p></div>' for h, p in items)
    st.markdown(f'<h2 class="sec">{title}</h2><div class="info">{cells}</div>', unsafe_allow_html=True)


def days_text(n):
    if n < 0:
        return f":red[{-n} {'day' if n == -1 else 'days'} overdue]"
    return ":orange[Due today]" if n == 0 else f":{'orange' if n <= 3 else 'green'}[{n} {'day' if n == 1 else 'days'} left]"


ICON_BIG = ICON.replace('width="34" height="34"', 'width="56" height="56"')
SLIDES = [("New this month", "Fresh titles on the shelves", "Fiction"), ("Reader favourites", "Loved by our members", "Mystery"),
          ("For young readers", "Picture books and read-alouds", "Children"), ("Science and discovery", "Curious minds welcome", "Science")]
WALL = [("Fiction", "Stories to get lost in"), ("Mystery", "Clues, suspects and twists"), ("Science Fiction", "Other worlds, other futures")]


@st.cache_data(show_spinner=False)
def data_uri(path, mtime):
    ext = path.rsplit(".", 1)[-1].lower()
    with open(path, "rb") as f:
        return f"data:image/{'jpeg' if ext in ('jpg', 'jpeg') else ext};base64," + base64.b64encode(f.read()).decode()


def big_slot(kind, i, title, sub, color):
    """A big poster (banner-1.jpg ... or wall-1.jpg ... in posters/). Empty space until you add the file."""
    for e in ("jpg", "jpeg", "png", "webp"):
        p = os.path.join(POSTERS, f"{kind}-{i}.{e}")
        if os.path.isfile(p):
            inner = f'<img src="{data_uri(p, os.path.getmtime(p))}" alt="{html.escape(title)}">'
            break
    else:
        inner = f"{ICON_BIG}<b>Big poster image</b><span>posters/{kind}-{i}.jpg</span>"
    return f'<div class="big" style="--c:{color}">{inner}<div class="cap"><b>{html.escape(title)}</b><span>{html.escape(sub)}</span></div></div>'


def slider_html():
    slides = "".join(f'<div class="slide">{big_slot("banner", i + 1, t, s, CATS[c])}</div>' for i, (t, s, c) in enumerate(SLIDES))
    return f'<div class="slider">{slides}<div class="dots">{"<i></i>" * len(SLIDES)}</div></div>'


def wall_html():
    cells = "".join(big_slot("wall", i + 1, t, s, CATS[t]) for i, (t, s) in enumerate(WALL))
    return f'<h2 class="sec">Poster wall</h2><div class="wall">{cells}</div>'


def menu(label):
    """A pop-up menu (st.popover on Streamlit 1.31+, otherwise an expander)."""
    return st.popover(label) if hasattr(st, "popover") else st.expander(label)


def sign_toggle():
    s = st.session_state
    if me():
        s.user, s.returning, s.auth_mode, s.nav, s.flash = None, True, "in", "home", "Signed out"
    else:
        s.nav = "auth"


def auth_label():
    return "Sign out" if me() else ("Sign in" if st.session_state.get("returning") else "Create account")


def popup_menus():
    _, a, b, _ = st.columns([3, 1, 1, 3])
    with a:
        with menu("Categories"):
            st.button("All books", key="pm-all", on_click=go, args=("catalog",))
            for c in categories():
                st.button(c, key=f"pm-{c}", on_click=go, args=("catalog", c))
    with b:
        with menu("Account"):
            for i, t in enumerate(("Books on loan", "Reservations", "Returned books")):
                st.button(t, key=f"pm-acc{i}", on_click=go, args=("account",))
            st.button(auth_label(), key="pm-auth", on_click=sign_toggle)


def sidebar_menu():
    with st.sidebar:
        st.markdown(f'<div class="sbhead">{LOGO}<b>BookQ</b></div>', unsafe_allow_html=True)
        st.caption(f"Signed in as {first_name()}" if me() else "Welcome to BookQ")
        st.button("Home", key="sb-home", on_click=go, args=("home",))
        st.button("All books", key="sb-all", on_click=go, args=("catalog",))
        st.caption("Categories")
        for c in categories():
            st.button(c, key=f"sb-{c}", on_click=go, args=("catalog", c))
        st.caption("My library")
        for i, t in enumerate(("Books on loan", "Reservations", "Returned books")):
            st.button(t, key=f"sb-acc{i}", on_click=go, args=("account",))
        st.button(auth_label(), key="sb-auth", on_click=sign_toggle)


# ----------------------------------------------------------------------- pages
def page_home():
    st.markdown('<div class="hero"><h2>Find your next read</h2><p>Search the BookQ collection, borrow or reserve in a few clicks, and manage your loans online.</p></div>', unsafe_allow_html=True)
    _, mid, btn, _ = st.columns([1, 4, 1, 1])
    mid.text_input("Search the catalog", key="hq", placeholder="Search by title, author or ISBN", label_visibility="collapsed")
    btn.button("Search", on_click=lambda: go("catalog", text=st.session_state.get("hq", "")))
    st.markdown(slider_html(), unsafe_allow_html=True)
    st.markdown('<div class="strip"><div><b>14 days</b><span>per loan</span></div><div><b>5 books</b><span>at a time</span></div>'
                '<div><b>1 renewal</b><span>online, in one click</span></div><div><b>Reserve</b><span>any title that is out</span></div></div>', unsafe_allow_html=True)
    blocks("About BookQ", ABOUT)
    st.markdown('<h2 class="sec">Browse by category</h2>', unsafe_allow_html=True)
    cats = categories()
    for i in range(0, len(cats), 4):
        for col, c in zip(st.columns(4), cats[i:i + 4]):
            col.button(c, key=f"tile-{c}", on_click=go, args=("catalog", c))
    shelf("Featured books", pick(), "feat")
    st.button("View the full catalog", on_click=go, args=("catalog",))
    st.markdown(wall_html(), unsafe_allow_html=True)
    shelf("More to explore", pick(skip=16), "more")
    for title, c, w in (("Mystery picks", "Mystery", "myst"), ("Science fiction picks", "Science Fiction", "scifi"), ("For young readers", "Children", "kids")):
        shelf(title, pick(" WHERE cat=?", (c,)), w, c)
    st.markdown('<h2 class="sec">How it works</h2><div class="info">' + "".join(f'<div class="blk"><h3>{h}</h3><p>{p}</p></div>' for h, p in STEPS) + "</div>", unsafe_allow_html=True)
    blocks("Learning Oracle and PL/SQL", ORACLE_PATH)
    blocks("PL/SQL at a glance", PLSQL_REF)
    blocks("Issuing, reserving and returning", RULES)
    blocks("Reading tips", TIPS)
    blocks("Events and programmes (samples)", EVENTS)
    st.markdown('<h2 class="sec">Frequently asked questions</h2>', unsafe_allow_html=True)
    for q, a in FAQ:
        with st.expander(q):
            st.write(a)
    label = "Go to My account" if me() else ("Sign in" if st.session_state.get("returning") else "Create account")
    st.markdown('<div class="cta"><h2>Ready to start reading?</h2><p>Create an account to borrow, reserve and keep track of every book you read.</p></div>', unsafe_allow_html=True)
    _, b, c, _ = st.columns([2, 1, 1, 2])
    b.button(label, key="cta1", on_click=lambda: st.session_state.update(nav="account" if me() else "auth"))
    c.button("Browse the catalog", key="cta2", on_click=go, args=("catalog",))
    blocks("Good to know", GOOD)


def page_catalog():
    s = st.session_state
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    text = c1.text_input("Search", key="q", placeholder="Title, author, ISBN")
    cat = c2.selectbox("Category", ["All categories"] + categories(), key="fc")
    avail = c3.selectbox("Availability", ["Any", "Available now", "All on loan"], key="fa")
    sort = c4.selectbox("Sort by", list(SORTS), key="fs")
    sql, args = f"SELECT * FROM ({BOOKS_SQL}) WHERE 1=1", []
    if text:
        sql += " AND UPPER(title||' '||author||' '||isbn||' '||cat) LIKE UPPER(?)"
        args.append(f"%{text}%")
    if cat != "All categories":
        sql += " AND cat=?"
        args.append(cat)
    if avail == "Available now":
        sql += " AND avail>0"
    elif avail == "All on loan":
        sql += " AND avail<1"
    rows = run(sql + f" ORDER BY {SORTS[sort]}", tuple(args))
    if s.get("sig") != (text, cat, avail, sort):
        s.sig, s.pg = (text, cat, avail, sort), 0
    pages = max(1, math.ceil(len(rows) / PER_PAGE))
    pg = min(s.get("pg", 0), pages - 1)
    chunk = rows[pg * PER_PAGE:(pg + 1) * PER_PAGE]
    if not chunk:
        st.info("No titles match. Try a shorter search or clear the filters.")
    for i in range(0, len(chunk), PER_ROW):          # posters sit side by side in rows
        for col, b in zip(st.columns(PER_ROW), chunk[i:i + PER_ROW]):
            with col:
                card(b, "cat")
    if pages > 1:
        _, a, m, z, _ = st.columns([3, 1, 1, 1, 3])
        a.button("Previous", disabled=pg < 1, on_click=lambda: s.update(pg=pg - 1))
        m.markdown(f"Page {pg + 1} of {pages}")
        z.button("Next", disabled=pg >= pages - 1, on_click=lambda: s.update(pg=pg + 1))


def page_auth():
    s = st.session_state
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        if s.get("auth_msg"):
            st.warning(s.auth_msg)
        up = s.get("auth_mode", "up") == "up"
        if up:
            st.subheader("Create your account")
            with st.form("signup"):
                st.text_input("Full name", key="su_name")
                st.text_input("Username", key="su_user", help="3 to 20 lowercase letters, numbers or underscores")
                st.text_input("Password (at least 6 characters)", key="su_pass", type="password")
                st.form_submit_button("Create account", on_click=do_signup)
            st.caption("Already have an account?")
            st.button("Sign in", on_click=set_mode, args=("in",))
        else:
            st.subheader("Sign in to BookQ")
            with st.form("signin"):
                st.text_input("Username", key="si_user")
                st.text_input("Password", key="si_pass", type="password")
                st.form_submit_button("Sign in", on_click=do_signin)
            st.caption("Demo accounts: asha, rohan or priya. Password: bookq123")
            st.caption("New to BookQ?")
            st.button("Create an account", on_click=set_mode, args=("up",))
        if s.get("auth_err"):
            st.error(s.auth_err)
        st.caption("Every person signs in separately, so each account sees only its own loans, reservations and history.")


def page_account():
    if not me():
        st.session_state.setdefault("auth_msg", "Sign in to see your loans, reservations and history.")
        return page_auth()
    u = me()
    loans = run("SELECT l.id AS lid, l.issued, l.due, l.renewed, b.id, b.title, b.author, b.cat, b.poster FROM loans l "
                "JOIN books b ON b.id=l.book_id WHERE l.username=? ORDER BY l.due", (u,))
    holds = run(BOOKS_SQL.replace("SELECT b.*", "SELECT b.*, h.book_id AS hid") + " JOIN holds h ON h.book_id=b.id WHERE h.username=?", (u,))
    hist = run("SELECT h.issued, h.returned, b.title FROM history h JOIN books b ON b.id=h.book_id WHERE h.username=? ORDER BY h.id DESC", (u,))
    days = lambda d: (date.fromisoformat(d) - date.today()).days
    st.header(f"Hello, {first_name()}")
    st.caption("Everything you have issued, what is on loan and what is coming up.")
    stats = [("On loan (limit 5)", len(loans)), ("Due within 3 days", sum(0 <= days(l["due"]) <= 3 for l in loans)),
             ("Overdue", sum(days(l["due"]) < 0 for l in loans)), ("Reservations", len(holds)), ("Returned", len(hist))]
    for col, (label, v) in zip(st.columns(5), stats):
        col.metric(label, v)
    st.subheader("Books on loan")
    if not loans:
        st.info("You have no books on loan. Find something in the catalog.")
    for l in loans:
        with st.container(border=True):
            a, b, c, d = st.columns([1, 5, 1, 1])
            with a:
                show_poster(l, mini=True)
            b.markdown(f"**{l['title']}**  \n{l['author']} · {l['cat']}  \nIssued {l['issued']} · Due {l['due']} · {days_text(days(l['due']))}" + (" (renewed)" if l["renewed"] else ""))
            c.button("Renew", key=f"rn{l['lid']}", on_click=renew, args=(l["lid"],))
            d.button("Return", key=f"rt{l['lid']}", on_click=give_back, args=(l["lid"],))
    st.subheader("Reservations")
    if not holds:
        st.info("No reservations.")
    for h in holds:
        a, b, c, d = st.columns([5, 3, 1, 1])
        a.write(h["title"])
        b.markdown(":green[Ready to borrow]" if h["avail"] > 0 else ":orange[Waiting for a copy]")
        if h["avail"] > 0:
            c.button("Borrow", key=f"hb{h['id']}", on_click=borrow, args=(h["id"],))
        d.button("Cancel", key=f"hc{h['id']}", on_click=unhold, args=(h["id"],))
    st.subheader("Returned books")
    if not hist:
        st.info("Books you return will be listed here.")
    for r in hist:
        a, b, c = st.columns([5, 2, 2])
        a.write(r["title"])
        b.caption(f"Issued {r['issued']}")
        c.caption(f"Returned {r['returned']}")
    st.caption(f"Loans last {LOAN_DAYS} days and can be renewed once, unless someone else has reserved the book.")


# ------------------------------------------------------------------------ main
st.set_page_config(page_title="BookQ", page_icon="📚", layout="wide", initial_sidebar_state="collapsed")
init_db()
css = CSS
for key, val in backgrounds().items():
    css = css.replace(key, val)
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
st.session_state.setdefault("nav", "home")
if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))
st.markdown(f'<div class="top"><div class="logo">{LOGO}</div><h1>BookQ</h1><p>Where every story begins</p></div>', unsafe_allow_html=True)
st.radio("Menu", ["home", "catalog", "account", "auth"], key="nav", horizontal=True, label_visibility="collapsed",
         format_func=nav_label, on_change=nav_changed)
popup_menus()
sidebar_menu()
{"home": page_home, "catalog": page_catalog, "account": page_account, "auth": page_auth}[st.session_state.nav]()
st.markdown('<div class="foot"><div class="g"><div><h3>BookQ</h3><p>A community library with a growing collection of fiction, non-fiction, children\'s books and technology titles.</p></div>'
            '<div><h3>Opening hours</h3><p>Mon to Fri: 9 am to 7 pm</p><p>Saturday: 10 am to 4 pm</p><p>Sunday: closed</p></div>'
            '<div><h3>Contact</h3><p>12 Library Road, Your City</p><p>info@bookq.example</p><p>Website: www.bookq.example</p></div></div>'
            '<div class="b">&copy; 2026 BookQ. Address and contact details are samples.</div></div>', unsafe_allow_html=True)
