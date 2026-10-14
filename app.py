import os
import uuid

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
from functools import wraps

app = Flask(__name__)
app.secret_key = "replace_with_a_fixed_secret_in_production"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB       = os.path.join(BASE_DIR, "users.db")

UPLOAD_FOLDER      = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

# ─────────────────────────────────────────────────────────────────────────────
# UC Schools Data
# ─────────────────────────────────────────────────────────────────────────────
UC_SCHOOLS = [
    { "id": "berkeley", "name": "UC Berkeley",     "short": "CAL",  "logo": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Seal_of_University_of_California%2C_Berkeley.svg" },
    { "id": "ucla",     "name": "UC Los Angeles",  "short": "UCLA", "logo": "https://upload.wikimedia.org/wikipedia/commons/0/0d/The_University_of_California_UCLA.svg" },
    { "id": "ucsd",     "name": "UC San Diego",    "short": "UCSD", "logo": "https://upload.wikimedia.org/wikipedia/commons/c/c1/Seal_of_the_University_of_California%2C_San_Diego.svg" },
    { "id": "ucsb",     "name": "UC Santa Barbara","short": "UCSB", "logo": "https://upload.wikimedia.org/wikipedia/commons/4/48/UC_Santa_Barbara_Seal.png" },
    { "id": "uci",      "name": "UC Irvine",       "short": "UCI",  "logo": "https://upload.wikimedia.org/wikipedia/commons/b/b0/The_University_of_California_Irvine.svg" },
    { "id": "ucd",      "name": "UC Davis",        "short": "UCD",  "logo": "https://upload.wikimedia.org/wikipedia/commons/f/f3/The_University_of_California_Davis.svg" },
    { "id": "ucsc",     "name": "UC Santa Cruz",   "short": "UCSC", "logo": "https://upload.wikimedia.org/wikipedia/commons/5/53/The_University_of_California_1868_UCSC.svg" },
    { "id": "ucr",      "name": "UC Riverside",    "short": "UCR",  "logo": "https://upload.wikimedia.org/wikipedia/en/5/51/UC_Riverside_seal.svg" },
    { "id": "ucm",      "name": "UC Merced",       "short": "UCM",  "logo": "https://upload.wikimedia.org/wikipedia/en/5/51/UC_Merced_Seal.png" },
]

# Map campus registration name → school id
CAMPUS_TO_ID = {
    "UC Berkeley":     "berkeley",
    "UC Los Angeles":  "ucla",
    "UC San Diego":    "ucsd",
    "UC Santa Barbara":"ucsb",
    "UC Irvine":       "uci",
    "UC Davis":        "ucd",
    "UC Santa Cruz":   "ucsc",
    "UC Riverside":    "ucr",
    "UC Merced":       "ucm",
}

# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    UNIQUE NOT NULL,
                password TEXT    NOT NULL,
                campus   TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                caption    TEXT,
                photo_path TEXT,
                links      TEXT,
                votes      INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS upvotes (
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, post_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                follower_id INTEGER NOT NULL,
                followed_id INTEGER NOT NULL,
                PRIMARY KEY (follower_id, followed_id),
                FOREIGN KEY (follower_id) REFERENCES users(id),
                FOREIGN KEY (followed_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id      TEXT    PRIMARY KEY,
                post_id INTEGER NOT NULL,
                name    TEXT,
                brand   TEXT,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS closet (
                user_id INTEGER NOT NULL,
                item_id TEXT    NOT NULL,
                PRIMARY KEY (user_id, item_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (item_id) REFERENCES items(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, post_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS link_clicks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id    INTEGER NOT NULL,
                url        TEXT    NOT NULL,
                clicked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """)
        conn.commit()
    print("Database initialised. DB path:", DB)


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def attach_items_to_posts(conn, posts_list):
    """Takes a list of DB row posts, fetches their items, returns dicts with imageUrl/userName."""
    formatted = []
    for post in posts_list:
        post_dict = dict(post)
        db_items  = conn.execute(
            "SELECT id, name, brand FROM items WHERE post_id = ?", (post["id"],)
        ).fetchall()
        post_dict["items"]    = [{"id": i["id"], "name": i["name"], "brand": i["brand"]} for i in db_items]
        post_dict["imageUrl"] = url_for("static", filename=post["photo_path"]) if post["photo_path"] else ""
        post_dict["userName"] = post["username"] if "username" in post.keys() else ""

        # Attach per-URL click counts for this post
        if post_dict.get("links"):
            click_rows = conn.execute(
                "SELECT url, COUNT(*) as cnt FROM link_clicks WHERE post_id = ? GROUP BY url",
                (post["id"],)
            ).fetchall()
            post_dict["link_clicks"] = {row["url"]: row["cnt"] for row in click_rows}
        else:
            post_dict["link_clicks"] = {}

        formatted.append(post_dict)
    return formatted


# ─────────────────────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["campus"]   = user["campus"]
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="No account found with that username or password.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm",  "")
        campus   = request.form.get("campus",   "").strip()

        if not username or not password or not campus:
            flash("All fields are required.")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match.")
            return render_template("register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return render_template("register.html")

        hashed = generate_password_hash(password, method="pbkdf2:sha256")

        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (username, password, campus) VALUES (?, ?, ?)",
                    (username, hashed, campus)
                )
                conn.commit()
        except sqlite3.IntegrityError:
            flash("That username is already taken.")
            return render_template("register.html")

        flash("Account created! Please sign in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────────────────────
# Home page  (Following + Your Campus sections)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/home")
@login_required
def home():
    current_uid  = session["user_id"]
    user_campus  = session.get("campus", "")
    campus_id    = CAMPUS_TO_ID.get(user_campus, "")
    campus_short = next((s["short"] for s in UC_SCHOOLS if s["id"] == campus_id), user_campus)

    with get_db() as conn:
        # People the current user follows
        followed_ids = [
            row["followed_id"] for row in conn.execute(
                "SELECT followed_id FROM follows WHERE follower_id = ?", (current_uid,)
            ).fetchall()
        ]

        # Posts from followed users
        following_posts = []
        if followed_ids:
            placeholders = ",".join("?" * len(followed_ids))
            db_following = conn.execute(f"""
                SELECT p.*, u.username FROM posts p
                JOIN users u ON p.user_id = u.id
                WHERE p.user_id IN ({placeholders})
                ORDER BY p.created_at DESC LIMIT 30
            """, followed_ids).fetchall()
            following_posts = attach_items_to_posts(conn, db_following)

        # Posts from user's own campus (excluding own posts)
        campus_posts = []
        if user_campus:
            db_campus = conn.execute("""
                SELECT p.*, u.username FROM posts p
                JOIN users u ON p.user_id = u.id
                WHERE u.campus = ?
                ORDER BY p.votes DESC, p.created_at DESC LIMIT 12
            """, (user_campus,)).fetchall()
            campus_posts = attach_items_to_posts(conn, db_campus)

        # Saved closet items
        db_closet   = conn.execute("SELECT item_id FROM closet WHERE user_id = ?", (current_uid,)).fetchall()
        saved_items = [row["item_id"] for row in db_closet]

        # Who the user follows (for follow button state on home)
        following_set = set(followed_ids)

        # Liked post IDs (for heart button initial state)
        liked_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM likes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

    return render_template(
        "home.html",
        username        = session["username"],
        current_user_id = current_uid,
        user_campus     = user_campus,
        campus_short    = campus_short,
        following_posts = following_posts,
        campus_posts    = campus_posts,
        saved_items     = saved_items,
        following_set   = following_set,
        schools         = UC_SCHOOLS,
        liked_ids       = liked_ids,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Discover page  (all schools, browsable by campus)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/discover")
@login_required
def discover():
    current_uid  = session["user_id"]
    school_id    = request.args.get("school", "berkeley")
    school       = next((s for s in UC_SCHOOLS if s["id"] == school_id), UC_SCHOOLS[0])
    campus_name  = school["name"]

    with get_db() as conn:
        db_posts = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE u.campus = ?
            ORDER BY p.votes DESC, p.created_at DESC
            LIMIT 50
        """, (campus_name,)).fetchall()
        posts = attach_items_to_posts(conn, db_posts)

        db_closet   = conn.execute("SELECT item_id FROM closet WHERE user_id = ?", (current_uid,)).fetchall()
        saved_items = [row["item_id"] for row in db_closet]

        followed_ids = set(
            row["followed_id"] for row in conn.execute(
                "SELECT followed_id FROM follows WHERE follower_id = ?", (current_uid,)
            ).fetchall()
        )

        liked_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM likes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

    return render_template(
        "discover.html",
        username        = session["username"],
        current_user_id = current_uid,
        schools         = UC_SCHOOLS,
        active_school   = school,
        posts           = posts,
        saved_items     = saved_items,
        followed_ids    = list(followed_ids),
        liked_ids       = list(liked_ids),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main page  (Profile + Leaderboard tabs — the old SPA)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/main")
@login_required
def main_page():
    current_uid  = session["user_id"]
    profile_sort = request.args.get("sort", "newest")

    with get_db() as conn:
        # Profile posts
        profile_order = (
            "ORDER BY votes DESC, created_at DESC"
            if profile_sort == "popular"
            else "ORDER BY created_at DESC"
        )
        db_profile_posts = conn.execute(
            f"SELECT p.*, u.username FROM posts p JOIN users u ON p.user_id = u.id WHERE p.user_id = ? {profile_order}",
            (current_uid,)
        ).fetchall()
        profile_posts = attach_items_to_posts(conn, db_profile_posts)

        profile_stats = conn.execute("""
            SELECT COUNT(*) AS post_count,
                   COALESCE(SUM(votes), 0) AS total_votes
            FROM posts WHERE user_id = ?
        """, (current_uid,)).fetchone()

        # Leaderboard — top 3
        db_top3 = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.votes DESC, p.created_at DESC LIMIT 3
        """).fetchall()
        top3 = attach_items_to_posts(conn, db_top3)

        # Most recent (excluding top3)
        db_recent = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC LIMIT 30
        """).fetchall()
        recent = attach_items_to_posts(conn, db_recent)

        # Trend tracker
        db_trend = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.links IS NOT NULL AND p.links != ''
            ORDER BY p.votes DESC, p.created_at DESC LIMIT 10
        """).fetchall()
        trend = attach_items_to_posts(conn, db_trend)

        # Upvotes by current user
        upvoted_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM upvotes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

        db_closet   = conn.execute("SELECT item_id FROM closet WHERE user_id = ?", (current_uid,)).fetchall()
        saved_items = [row["item_id"] for row in db_closet]

        # Liked posts (private — only shown to the user themselves)
        db_liked = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            JOIN likes l ON l.post_id = p.id
            WHERE l.user_id = ?
            ORDER BY p.created_at DESC
        """, (current_uid,)).fetchall()
        liked_posts = attach_items_to_posts(conn, db_liked)

        liked_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM likes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

        # Per-URL click counts for own posts
        own_click_rows = conn.execute(
            "SELECT post_id, url, COUNT(*) as cnt FROM link_clicks "
            "WHERE post_id IN (SELECT id FROM posts WHERE user_id = ?) "
            "GROUP BY post_id, url",
            (current_uid,)
        ).fetchall()
        own_click_totals = {}
        for row in own_click_rows:
            own_click_totals.setdefault(row["post_id"], {})[row["url"]] = row["cnt"]

    return render_template(
        "main.html",
        username         = session["username"],
        campus           = session.get("campus", ""),
        current_user_id  = current_uid,
        profile_posts    = profile_posts,
        profile_stats    = profile_stats,
        profile_sort     = profile_sort,
        top3             = top3,
        recent           = recent,
        trend            = trend,
        upvoted_ids      = upvoted_ids,
        schools          = UC_SCHOOLS,
        saved_items      = saved_items,
        liked_posts      = liked_posts,
        liked_ids        = liked_ids,
        own_click_totals = own_click_totals,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Profile (own shortcut + public profile)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/profile")
@login_required
def profile_self():
    return redirect(url_for("main_page") + "#profile")


@app.route("/profile/<int:uid>")
@login_required
def profile(uid):
    current_uid = session["user_id"]
    if uid == current_uid:
        return redirect(url_for("main_page") + "#profile")

    with get_db() as conn:
        owner = conn.execute(
            "SELECT id, username, campus FROM users WHERE id = ?", (uid,)
        ).fetchone()

        if owner is None:
            flash("User not found.")
            return redirect(url_for("home"))

        sort  = request.args.get("sort", "newest")
        order = "ORDER BY votes DESC, created_at DESC" if sort == "popular" else "ORDER BY created_at DESC"

        stats = conn.execute("""
            SELECT COUNT(*) AS post_count,
                   COALESCE(SUM(votes), 0) AS total_votes
            FROM posts WHERE user_id = ?
        """, (uid,)).fetchone()

        db_posts = conn.execute(
            f"SELECT p.*, u.username FROM posts p JOIN users u ON p.user_id = u.id WHERE p.user_id = ? {order}", (uid,)
        ).fetchall()
        posts = attach_items_to_posts(conn, db_posts)

        upvoted_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM upvotes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

        is_following = bool(conn.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?",
            (current_uid, uid)
        ).fetchone())

        # Per-post link click totals for the profile owner to see
        click_totals = {}
        if True:  # always fetch so owner can see counts
            rows = conn.execute(
                "SELECT post_id, url, COUNT(*) as cnt FROM link_clicks WHERE post_id IN "
                "(SELECT id FROM posts WHERE user_id = ?) GROUP BY post_id, url",
                (uid,)
            ).fetchall()
            for row in rows:
                click_totals.setdefault(row["post_id"], {})[row["url"]] = row["cnt"]

    return render_template(
        "profile.html",
        owner          = owner,
        posts          = posts,
        stats          = stats,
        sort           = sort,
        upvoted_ids    = upvoted_ids,
        is_own_profile = False,
        is_following   = is_following,
        current_uid    = current_uid,
        click_totals   = click_totals,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Follow / Unfollow (toggle)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/follow/<int:uid>", methods=["POST"])
@login_required
def follow(uid):
    current_uid = session["user_id"]
    if uid == current_uid:
        return jsonify({"status": "error", "message": "Cannot follow yourself"}), 400

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followed_id = ?",
            (current_uid, uid)
        ).fetchone()

        if existing:
            conn.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followed_id = ?",
                (current_uid, uid)
            )
            status = "unfollowed"
        else:
            conn.execute(
                "INSERT INTO follows (follower_id, followed_id) VALUES (?, ?)",
                (current_uid, uid)
            )
            status = "followed"
        conn.commit()

    return jsonify({"status": status, "uid": uid})


# ─────────────────────────────────────────────────────────────────────────────
# Closet Toggle
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/toggle_closet", methods=["POST"])
@login_required
def toggle_closet():
    data        = request.get_json()
    item_id     = data.get("item_id")
    current_uid = session["user_id"]

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM closet WHERE user_id = ? AND item_id = ?",
            (current_uid, item_id)
        ).fetchone()

        if existing:
            conn.execute(
                "DELETE FROM closet WHERE user_id = ? AND item_id = ?",
                (current_uid, item_id)
            )
            status = "removed"
        else:
            conn.execute(
                "INSERT INTO closet (user_id, item_id) VALUES (?, ?)",
                (current_uid, item_id)
            )
            status = "added"
        conn.commit()

    return jsonify({"status": status, "item_id": item_id})


# ─────────────────────────────────────────────────────────────────────────────
# Upload a post
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/upload_post", methods=["POST"])
@login_required
def upload_post():
    caption    = request.form.get("caption", "").strip()
    links      = request.form.get("links",   "").strip()
    photo      = request.files.get("photo")
    photo_path = None

    if photo and photo.filename and allowed_file(photo.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ext      = secure_filename(photo.filename).rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        photo.save(os.path.join(UPLOAD_FOLDER, filename))
        photo_path = f"uploads/{filename}"

    with get_db() as conn:
        conn.execute(
            "INSERT INTO posts (user_id, caption, photo_path, links) VALUES (?, ?, ?, ?)",
            (session["user_id"], caption or None, photo_path, links or None)
        )
        conn.commit()

    flash("Your look has been posted!")
    return redirect(url_for("main_page") + "#profile")


# ─────────────────────────────────────────────────────────────────────────────
# Upvote (toggle)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/upvote/<int:post_id>", methods=["POST"])
@login_required
def upvote(post_id):
    current_uid = session["user_id"]
    referrer    = request.referrer or url_for("home")

    with get_db() as conn:
        already = conn.execute(
            "SELECT 1 FROM upvotes WHERE user_id = ? AND post_id = ?",
            (current_uid, post_id)
        ).fetchone()

        if already:
            conn.execute("DELETE FROM upvotes WHERE user_id = ? AND post_id = ?", (current_uid, post_id))
            conn.execute("UPDATE posts SET votes = MAX(0, votes - 1) WHERE id = ?", (post_id,))
        else:
            conn.execute("INSERT INTO upvotes (user_id, post_id) VALUES (?, ?)", (current_uid, post_id))
            conn.execute("UPDATE posts SET votes = votes + 1 WHERE id = ?", (post_id,))
        conn.commit()

    return redirect(referrer)


# ─────────────────────────────────────────────────────────────────────────────
# Like (toggle) — saves post to user's private liked posts
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like_post(post_id):
    current_uid = session["user_id"]
    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM likes WHERE user_id = ? AND post_id = ?",
            (current_uid, post_id)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM likes WHERE user_id = ? AND post_id = ?", (current_uid, post_id))
            status = "unliked"
        else:
            conn.execute("INSERT INTO likes (user_id, post_id) VALUES (?, ?)", (current_uid, post_id))
            status = "liked"
        conn.commit()
    return jsonify({"status": status, "post_id": post_id})


# ─────────────────────────────────────────────────────────────────────────────
# Track link click + redirect
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/track_link/<int:post_id>")
@login_required
def track_link(post_id):
    url = request.args.get("url", "").strip()
    if not url:
        return redirect("/")
    # Record the click
    with get_db() as conn:
        conn.execute(
            "INSERT INTO link_clicks (post_id, url) VALUES (?, ?)",
            (post_id, url)
        )
        conn.commit()
    # Redirect to the actual URL
    if not url.startswith("http"):
        url = "https://" + url
    return redirect(url)


# ─────────────────────────────────────────────────────────────────────────────
# Delete own post
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/delete_post/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    current_uid = session["user_id"]

    with get_db() as conn:
        post = conn.execute(
            "SELECT * FROM posts WHERE id = ? AND user_id = ?",
            (post_id, current_uid)
        ).fetchone()

        if post:
            if post["photo_path"]:
                full_path = os.path.join(BASE_DIR, "static", post["photo_path"])
                if os.path.exists(full_path):
                    os.remove(full_path)
            conn.execute("DELETE FROM items      WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM upvotes    WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM likes      WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM link_clicks WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM posts      WHERE id = ?",      (post_id,))
            conn.commit()
        else:
            flash("Post not found or you don't have permission.")

    return redirect(url_for("main_page") + "#profile")


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard standalone page
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/leaderboard")
@login_required
def leaderboard():
    current_uid = session["user_id"]

    with get_db() as conn:
        # Top 3
        db_top3 = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.votes DESC, p.created_at DESC LIMIT 3
        """).fetchall()
        top3 = attach_items_to_posts(conn, db_top3)

        # Most recent
        db_rest = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC LIMIT 30
        """).fetchall()
        rest = attach_items_to_posts(conn, db_rest)

        # Trend tracker
        db_trend = conn.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.votes DESC, p.created_at DESC LIMIT 10
        """).fetchall()
        trend = attach_items_to_posts(conn, db_trend)

        upvoted_ids = set(
            row["post_id"] for row in conn.execute(
                "SELECT post_id FROM upvotes WHERE user_id = ?", (current_uid,)
            ).fetchall()
        )

    return render_template(
        "leaderboard.html",
        top3        = top3,
        rest        = rest,
        trend       = trend,
        upvoted_ids = upvoted_ids,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)