import os
import sqlite3
import uuid
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "villagestay.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
PLATFORM_FEE, CARETAKER_FEE = 0.10, 0.05

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB uploads

LIST_SQL = ("SELECT p.*, (SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.property_id=p.id) "
            "AS avg_rating FROM properties p")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    os.makedirs(UPLOADS, exist_ok=True)
    with sqlite3.connect(DB) as con:
        with open(os.path.join(BASE, "schema.sql")) as f:
            con.executescript(f.read())
        if not con.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            con.execute("INSERT INTO users(name,email,password,role) VALUES (?,?,?,?)",
                        ("Admin", "admin@villagestay.com", generate_password_hash("admin123", method="pbkdf2:sha256"), "admin"))


def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("This page is not available for your account type.")
                return redirect(url_for("index"))
            return f(*a, **kw)
        return wrapper
    return deco


def split(rent, caretaker):
    fee = round(rent * PLATFORM_FEE)
    care = round(rent * CARETAKER_FEE) if caretaker else 0
    return {"fee": fee, "care": care, "owner": rent - fee - care}


def save_image(file):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOADS, name))
    return name


def read_form():
    f = request.form
    try:
        rent = int(f["rent"])
    except ValueError:
        rent = 0
    ok = f["title"].strip() and f["village"].strip() and rent > 0 \
        and f["stay_type"] in ("experience", "long_term")
    return f, rent, bool(ok)


# ---------- browsing ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    stay_type = request.args.get("stay_type", "")
    max_rent = request.args.get("max_rent", "").strip()
    sql, args = LIST_SQL + " WHERE p.status='available'", []
    if q:
        sql += " AND (p.village LIKE ? OR p.state LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if stay_type in ("experience", "long_term"):
        sql += " AND p.stay_type=?"
        args.append(stay_type)
    if max_rent.isdigit():
        sql += " AND p.rent<=?"
        args.append(int(max_rent))
    props = get_db().execute(sql + " ORDER BY p.verified DESC, p.id DESC", args).fetchall()
    return render_template("index.html", properties=props, q=q, stay_type=stay_type,
                           max_rent=max_rent, heading="Stay in a village home")


@app.route("/saved")
@login_required("guest")
def saved():
    props = get_db().execute(LIST_SQL + " JOIN favorites f ON f.property_id=p.id WHERE f.user_id=?",
                             (session["user_id"],)).fetchall()
    return render_template("index.html", properties=props, saved=True, heading="Saved homes")


@app.route("/property/<int:pid>")
def property_detail(pid):
    db = get_db()
    p = db.execute("SELECT p.*, u.name AS owner_name FROM properties p "
                   "JOIN users u ON u.id=p.owner_id WHERE p.id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    reviews = db.execute("SELECT r.*, u.name FROM reviews r JOIN users u ON u.id=r.guest_id "
                         "WHERE r.property_id=? ORDER BY r.id DESC", (pid,)).fetchall()
    avg = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None
    uid, is_fav, can_review = session.get("user_id"), False, False
    if uid and session["role"] == "guest":
        is_fav = bool(db.execute("SELECT 1 FROM favorites WHERE user_id=? AND property_id=?", (uid, pid)).fetchone())
        stayed = db.execute("SELECT 1 FROM bookings WHERE property_id=? AND guest_id=? AND status='approved'", (pid, uid)).fetchone()
        done = db.execute("SELECT 1 FROM reviews WHERE property_id=? AND guest_id=?", (pid, uid)).fetchone()
        can_review = bool(stayed and not done)
    return render_template("property.html", p=p, split=split(p["rent"], p["caretaker"]),
                           reviews=reviews, avg=avg, is_fav=is_fav, can_review=can_review)


# ---------- accounts ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        pw, role = request.form["password"], request.form["role"]
        if not name or not email or len(pw) < 6 or role not in ("owner", "guest"):
            flash("Fill all fields. Password needs 6+ characters.")
        else:
            try:
                db = get_db()
                db.execute("INSERT INTO users(name,email,password,role) VALUES (?,?,?,?)",
                           (name, email, generate_password_hash(pw, method="pbkdf2:sha256"), role))
                db.commit()
                flash("Account created. Please log in.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email is already registered.")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session.update(user_id=user["id"], role=user["role"], name=user["name"])
            return redirect(url_for("admin" if user["role"] == "admin" else "dashboard"))
        flash("Wrong email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- owner: manage listings ----------
@app.route("/property/new", methods=["GET", "POST"])
@login_required("owner")
def new_property():
    if request.method == "POST":
        f, rent, ok = read_form()
        if ok:
            db = get_db()
            db.execute("INSERT INTO properties(owner_id,title,village,state,description,rent,stay_type,caretaker,image)"
                       " VALUES (?,?,?,?,?,?,?,?,?)",
                       (session["user_id"], f["title"].strip(), f["village"].strip(), f["state"].strip(),
                        f["description"].strip(), rent, f["stay_type"], 1 if f.get("caretaker") else 0,
                        save_image(request.files.get("image"))))
            db.commit()
            flash("Property listed. An admin can mark it verified.")
            return redirect(url_for("dashboard"))
        flash("Please fill title, village and a valid rent.")
    return render_template("add_property.html", p=None)


@app.route("/property/<int:pid>/edit", methods=["GET", "POST"])
@login_required("owner")
def edit_property(pid):
    db = get_db()
    p = db.execute("SELECT * FROM properties WHERE id=? AND owner_id=?", (pid, session["user_id"])).fetchone()
    if not p:
        flash("Not allowed.")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        f, rent, ok = read_form()
        if ok:
            db.execute("UPDATE properties SET title=?,village=?,state=?,description=?,rent=?,stay_type=?,"
                       "caretaker=?,image=? WHERE id=?",
                       (f["title"].strip(), f["village"].strip(), f["state"].strip(), f["description"].strip(),
                        rent, f["stay_type"], 1 if f.get("caretaker") else 0,
                        save_image(request.files.get("image")) or p["image"], pid))
            db.commit()
            flash("Listing updated.")
            return redirect(url_for("property_detail", pid=pid))
        flash("Please fill title, village and a valid rent.")
    return render_template("add_property.html", p=p)


@app.route("/property/<int:pid>/delete", methods=["POST"])
@login_required("owner")
def delete_property(pid):
    db = get_db()
    if db.execute("SELECT 1 FROM properties WHERE id=? AND owner_id=?", (pid, session["user_id"])).fetchone():
        for t in ("bookings", "reviews", "favorites"):
            db.execute(f"DELETE FROM {t} WHERE property_id=?", (pid,))
        db.execute("DELETE FROM properties WHERE id=?", (pid,))
        db.commit()
        flash("Listing deleted.")
    return redirect(url_for("dashboard"))


# ---------- guest: bookings, reviews, favorites ----------
@app.route("/property/<int:pid>/request", methods=["POST"])
@login_required("guest")
def request_booking(pid):
    f, db = request.form, get_db()
    try:
        months = int(f["months"])
    except ValueError:
        months = 0
    if not db.execute("SELECT 1 FROM properties WHERE id=? AND status='available'", (pid,)).fetchone():
        flash("This home is no longer available.")
    elif not f["start_date"] or months < 1:
        flash("Choose a start date and number of months.")
    else:
        db.execute("INSERT INTO bookings(property_id,guest_id,start_date,months,message) VALUES (?,?,?,?,?)",
                   (pid, session["user_id"], f["start_date"], months, f["message"].strip()))
        db.commit()
        flash("Request sent to the owner.")
    return redirect(url_for("dashboard"))


@app.route("/booking/<int:bid>/cancel", methods=["POST"])
@login_required("guest")
def cancel_booking(bid):
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=? AND guest_id=?", (bid, session["user_id"])).fetchone()
    if b and b["status"] in ("pending", "approved"):
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
        if b["status"] == "approved":
            db.execute("UPDATE properties SET status='available' WHERE id=?", (b["property_id"],))
        db.commit()
        flash("Booking cancelled.")
    return redirect(url_for("dashboard"))


@app.route("/property/<int:pid>/review", methods=["POST"])
@login_required("guest")
def add_review(pid):
    db, uid = get_db(), session["user_id"]
    stayed = db.execute("SELECT 1 FROM bookings WHERE property_id=? AND guest_id=? AND status='approved'",
                        (pid, uid)).fetchone()
    try:
        rating = int(request.form["rating"])
    except ValueError:
        rating = 0
    if stayed and 1 <= rating <= 5:
        try:
            db.execute("INSERT INTO reviews(property_id,guest_id,rating,comment) VALUES (?,?,?,?)",
                       (pid, uid, rating, request.form["comment"].strip()))
            db.commit()
            flash("Thanks for your review.")
        except sqlite3.IntegrityError:
            flash("You already reviewed this home.")
    else:
        flash("Only guests with an approved stay can review.")
    return redirect(url_for("property_detail", pid=pid))


@app.route("/property/<int:pid>/favorite", methods=["POST"])
@login_required("guest")
def toggle_favorite(pid):
    db, uid = get_db(), session["user_id"]
    if db.execute("DELETE FROM favorites WHERE user_id=? AND property_id=?", (uid, pid)).rowcount == 0:
        db.execute("INSERT INTO favorites VALUES (?,?)", (uid, pid))
    db.commit()
    return redirect(url_for("property_detail", pid=pid))


# ---------- dashboards ----------
@app.route("/dashboard")
@login_required()
def dashboard():
    db, uid = get_db(), session["user_id"]
    if session["role"] == "admin":
        return redirect(url_for("admin"))
    if session["role"] == "owner":
        props = db.execute("SELECT * FROM properties WHERE owner_id=? ORDER BY id DESC", (uid,)).fetchall()
        reqs = db.execute("SELECT b.*, p.title, p.rent, p.caretaker, u.name AS guest_name FROM bookings b "
                          "JOIN properties p ON p.id=b.property_id JOIN users u ON u.id=b.guest_id "
                          "WHERE p.owner_id=? ORDER BY b.id DESC", (uid,)).fetchall()
        earned = sum(split(r["rent"], r["caretaker"])["owner"] * r["months"]
                     for r in reqs if r["status"] == "approved")
        return render_template("dashboard.html", props=props, reqs=reqs, earned=earned)
    reqs = db.execute("SELECT b.*, p.title FROM bookings b JOIN properties p ON p.id=b.property_id "
                      "WHERE b.guest_id=? ORDER BY b.id DESC", (uid,)).fetchall()
    return render_template("dashboard.html", props=[], reqs=reqs)


@app.route("/booking/<int:bid>/<action>", methods=["POST"])
@login_required("owner")
def booking_action(bid, action):
    db = get_db()
    b = db.execute("SELECT b.*, p.owner_id FROM bookings b JOIN properties p ON p.id=b.property_id "
                   "WHERE b.id=?", (bid,)).fetchone()
    if not b or b["owner_id"] != session["user_id"] or action not in ("approve", "reject"):
        flash("Not allowed.")
        return redirect(url_for("dashboard"))
    db.execute("UPDATE bookings SET status=? WHERE id=?", ("approved" if action == "approve" else "rejected", bid))
    if action == "approve":
        db.execute("UPDATE properties SET status='rented' WHERE id=?", (b["property_id"],))
    db.commit()
    return redirect(url_for("dashboard"))


# ---------- admin ----------
@app.route("/admin")
@login_required("admin")
def admin():
    db = get_db()
    stats = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("users", "properties", "bookings", "reviews")}
    props = db.execute("SELECT p.*, u.name AS owner_name FROM properties p "
                       "JOIN users u ON u.id=p.owner_id ORDER BY p.id DESC").fetchall()
    return render_template("admin.html", stats=stats, props=props)


@app.route("/admin/verify/<int:pid>", methods=["POST"])
@login_required("admin")
def verify(pid):
    db = get_db()
    db.execute("UPDATE properties SET verified = 1 - verified WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("admin"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
