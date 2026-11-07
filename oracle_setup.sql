-- BookQ schema for Oracle Database 12c or newer (identity columns, FETCH FIRST).
-- Run it with:  python setup_oracle.py        (or paste it into SQL Developer / SQL*Plus)
-- Statements are separated by a line that contains only "/".

CREATE TABLE books (
  id      NUMBER(10) GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title   VARCHAR2(300 CHAR) NOT NULL,
  author  VARCHAR2(300 CHAR),
  year    NUMBER(4),
  cat     VARCHAR2(60 CHAR),
  copies  NUMBER(3) DEFAULT 1 NOT NULL,
  isbn    VARCHAR2(30 CHAR),
  descr   VARCHAR2(1000 CHAR),
  poster  VARCHAR2(200 CHAR),
  CONSTRAINT books_copies_ck CHECK (copies >= 1)
)
/

CREATE TABLE users (
  username VARCHAR2(20 CHAR) PRIMARY KEY,
  name     VARCHAR2(100 CHAR) NOT NULL,
  salt     VARCHAR2(40 CHAR) NOT NULL,
  pw       VARCHAR2(128 CHAR) NOT NULL
)
/

CREATE TABLE loans (
  id       NUMBER(10) GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  book_id  NUMBER(10) NOT NULL REFERENCES books(id),
  username VARCHAR2(20 CHAR) NOT NULL REFERENCES users(username),
  issued   DATE DEFAULT TRUNC(SYSDATE) NOT NULL,
  due      DATE NOT NULL,
  renewed  NUMBER(1) DEFAULT 0 NOT NULL
)
/

CREATE TABLE holds (
  book_id  NUMBER(10) NOT NULL REFERENCES books(id),
  username VARCHAR2(20 CHAR) NOT NULL REFERENCES users(username),
  CONSTRAINT holds_pk PRIMARY KEY (book_id, username)
)
/

CREATE TABLE history (
  id       NUMBER(10) GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  book_id  NUMBER(10) NOT NULL REFERENCES books(id),
  username VARCHAR2(20 CHAR) NOT NULL REFERENCES users(username),
  issued   DATE,
  returned DATE
)
/

CREATE INDEX loans_user_ix ON loans(username)
/

CREATE INDEX loans_book_ix ON loans(book_id)
/

-- ---------------------------------------------------------------- PL/SQL package
CREATE OR REPLACE PACKAGE pkg_library AS
  c_max_loans CONSTANT PLS_INTEGER := 5;
  c_loan_days CONSTANT PLS_INTEGER := 14;

  FUNCTION copies_available(p_book_id IN NUMBER) RETURN NUMBER;
  PROCEDURE borrow_book(p_book_id IN NUMBER, p_user IN VARCHAR2, p_due OUT DATE);
  PROCEDURE return_book(p_loan_id IN NUMBER, p_user IN VARCHAR2);
  PROCEDURE renew_loan(p_loan_id IN NUMBER, p_user IN VARCHAR2, p_due OUT DATE);
  PROCEDURE reserve_book(p_book_id IN NUMBER, p_user IN VARCHAR2);
  PROCEDURE cancel_hold(p_book_id IN NUMBER, p_user IN VARCHAR2);
END pkg_library;
/

CREATE OR REPLACE PACKAGE BODY pkg_library AS

  -- copies on the shelf = total copies - copies on loan
  FUNCTION copies_available(p_book_id IN NUMBER) RETURN NUMBER IS
    v_copies books.copies%TYPE;
    v_loaned PLS_INTEGER;
  BEGIN
    SELECT copies INTO v_copies FROM books WHERE id = p_book_id;
    SELECT COUNT(*) INTO v_loaned FROM loans WHERE book_id = p_book_id;
    RETURN v_copies - v_loaned;
  END copies_available;

  PROCEDURE borrow_book(p_book_id IN NUMBER, p_user IN VARCHAR2, p_due OUT DATE) IS
    v_copies books.copies%TYPE;
    v_count  PLS_INTEGER;
  BEGIN
    BEGIN
      -- lock the book row so two people cannot take the last copy at the same time
      SELECT copies INTO v_copies FROM books WHERE id = p_book_id FOR UPDATE;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20006, 'Book not found');
    END;

    SELECT COUNT(*) INTO v_count FROM loans WHERE username = p_user;
    IF v_count >= c_max_loans THEN
      RAISE_APPLICATION_ERROR(-20001, 'Limit reached: ' || c_max_loans || ' books at a time');
    END IF;

    IF copies_available(p_book_id) < 1 THEN
      RAISE_APPLICATION_ERROR(-20002, 'No copies available');
    END IF;

    p_due := TRUNC(SYSDATE) + c_loan_days;
    INSERT INTO loans(book_id, username, issued, due, renewed)
    VALUES (p_book_id, p_user, TRUNC(SYSDATE), p_due, 0);

    DELETE FROM holds WHERE book_id = p_book_id AND username = p_user;
  END borrow_book;

  PROCEDURE return_book(p_loan_id IN NUMBER, p_user IN VARCHAR2) IS
  BEGIN
    -- the trigger trg_loans_to_history records the return in the history table
    DELETE FROM loans WHERE id = p_loan_id AND username = p_user;
    IF SQL%ROWCOUNT = 0 THEN
      RAISE_APPLICATION_ERROR(-20005, 'Loan not found');
    END IF;
  END return_book;

  PROCEDURE renew_loan(p_loan_id IN NUMBER, p_user IN VARCHAR2, p_due OUT DATE) IS
    v_loan  loans%ROWTYPE;
    v_holds PLS_INTEGER;
  BEGIN
    BEGIN
      SELECT * INTO v_loan FROM loans WHERE id = p_loan_id AND username = p_user FOR UPDATE;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20005, 'Loan not found');
    END;

    IF v_loan.renewed = 1 THEN
      RAISE_APPLICATION_ERROR(-20003, 'Already renewed once');
    END IF;

    SELECT COUNT(*) INTO v_holds FROM holds WHERE book_id = v_loan.book_id;
    IF v_holds > 0 THEN
      RAISE_APPLICATION_ERROR(-20004, 'Can''t renew: someone has reserved it');
    END IF;

    p_due := v_loan.due + c_loan_days;
    UPDATE loans SET due = p_due, renewed = 1 WHERE id = p_loan_id;
  END renew_loan;

  PROCEDURE reserve_book(p_book_id IN NUMBER, p_user IN VARCHAR2) IS
  BEGIN
    INSERT INTO holds(book_id, username) VALUES (p_book_id, p_user);
  EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
      NULL;   -- already reserved by this member
  END reserve_book;

  PROCEDURE cancel_hold(p_book_id IN NUMBER, p_user IN VARCHAR2) IS
  BEGIN
    DELETE FROM holds WHERE book_id = p_book_id AND username = p_user;
  END cancel_hold;

END pkg_library;
/

-- ------------------------------------------------------------------- trigger
-- Every loan that is deleted (returned) is copied into the history table.
CREATE OR REPLACE TRIGGER trg_loans_to_history
AFTER DELETE ON loans
FOR EACH ROW
BEGIN
  INSERT INTO history(book_id, username, issued, returned)
  VALUES (:OLD.book_id, :OLD.username, :OLD.issued, TRUNC(SYSDATE));
END;
/
