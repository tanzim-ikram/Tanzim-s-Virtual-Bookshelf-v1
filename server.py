import os
import re
import unicodedata
import hmac
from urllib.parse import quote
import csv
import io
from datetime import date
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, abort, Response, send_file
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
csrf = CSRFProtect(app)

# Database Created
app.config['SECRET_KEY'] = os.environ.get('MY_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('MY_DATABASE_URI') or 'sqlite:///books.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # Reject uploads larger than 5 MB
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Send logged-out visitors to the login page instead of a bare 401

# Book cover images are stored as files in static/img/covers/, named after the book title
COVERS_DIR = os.path.join(app.static_folder, 'img', 'covers')
ALLOWED_COVER_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
_cover_index = None  # Cache of {slug: filename}
_cover_index_stamp = None  # Folder modification time the cache was built from


def slugify(text):
    # Keeps letters/digits of any script (e.g. Bengali) and combining marks; everything else
    # (spaces, punctuation, apostrophes, zero-width joiners) becomes a single "-".
    text = unicodedata.normalize('NFC', (text or '').lower()).replace("'", '').replace('’', '')
    kept = ''.join(ch if unicodedata.category(ch)[0] in 'LMN' else '-' for ch in text)
    return re.sub(r'-+', '-', kept).strip('-')


def _covers_stamp():
    try:
        return os.stat(COVERS_DIR).st_mtime_ns
    except OSError:
        return None


def refresh_cover_index():
    global _cover_index, _cover_index_stamp
    _cover_index = {}
    _cover_index_stamp = _covers_stamp()
    if os.path.isdir(COVERS_DIR):
        for filename in os.listdir(COVERS_DIR):
            stem, ext = os.path.splitext(filename)
            if ext.lower() in ALLOWED_COVER_EXTENSIONS:
                _cover_index[slugify(stem)] = filename
    return _cover_index


def css_safe_url(url):
    """Percent-encode quotes/parentheses so a URL can't break out of CSS url('...') or an HTML attribute."""
    return quote(url, safe="/:?&=%#@+,;~.-_!$*") if url else url


def find_local_cover(title):
    # Rebuild when the folder changed, e.g. another worker saved an upload or files were copied in
    if _cover_index is None or _cover_index_stamp != _covers_stamp():
        refresh_cover_index()
    return _cover_index.get(slugify(title))


def save_cover_upload(file_storage, title):
    """Save an uploaded cover as static/img/covers/<slug-of-title>.<ext>. Returns True if saved."""
    if not file_storage or not file_storage.filename:
        return False
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_COVER_EXTENSIONS:
        return False
    slug = slugify(title)
    if not slug:
        return False
    os.makedirs(COVERS_DIR, exist_ok=True)
    # Remove an older cover for the same book (possibly with a different extension or name)
    old = find_local_cover(title)
    if old:
        os.remove(os.path.join(COVERS_DIR, old))
    file_storage.save(os.path.join(COVERS_DIR, slug + ext))
    refresh_cover_index()
    return True


def split_genres(genre_text):
    # Genres are stored as one string, separated by commas (sometimes newlines)
    return [g.strip() for g in re.split(r'[,\n]', genre_text or '') if g.strip()]


def get_unique_genres():
    genre_set = set()  # Use a set to store unique genres

    for book in Book.query.all():
        # Convert each genre to title case and add to the set
        for genre in split_genres(book.genre):
            genre_set.add(genre.title())

    # Sorted list for a consistent order
    return sorted(genre_set)


def title_taken(title, exclude_id=None):
    # Covers are matched by title slug, so two titles with the same slug would share a cover
    slug = slugify(title)
    return any(slugify(b.title) == slug for b in Book.query.all() if b.id != exclude_id)


def is_legacy_hash(stored):
    return not stored.startswith(('pbkdf2:', 'scrypt:'))


def verify_password(user, password):
    stored = user.password or ''
    if is_legacy_hash(stored):
        # Older accounts were saved as plain text; compare in constant time
        return hmac.compare_digest(stored.encode('utf-8'), password.encode('utf-8'))
    return check_password_hash(stored, password)


# CREATE TABLE IN DB

# Define the User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(250), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"


# Create book model
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), unique=True, nullable=False)
    author_name = db.Column(db.String(250), nullable=False)
    genre = db.Column(db.String(500), nullable=False)
    language = db.Column(db.String(250), nullable=True)
    page_num = db.Column(db.Integer, nullable=True)
    read_unread = db.Column(db.String(250), nullable=True)
    review = db.Column(db.String(1000), nullable=True)
    img_url = db.Column(db.String(250), nullable=True)

    @property
    def cover_src(self):
        # Prefer a self-hosted cover in static/img/covers/, fall back to the external URL
        filename = find_local_cover(self.title)
        if filename:
            return css_safe_url(url_for('static', filename=f'img/covers/{filename}'))
        return css_safe_url(self.img_url) or None

    @property
    def genre_list(self):
        return split_genres(self.genre)

    def serialize(self):
        return {
            'title': self.title,
            'author_name': self.author_name,
            'genre': self.genre,
            'language': self.language,
            'page_num': self.page_num,
            'read_unread': self.read_unread,
            'review': self.review,
            'img_url': self.img_url,
            'cover_src': self.cover_src
        }

    def __repr__(self):
        return f"<Book {self.title}>"


with app.app_context():
    db.create_all()  # Creates missing tables only; existing data is untouched


def get_book_or_404():
    # A missing, non-numeric or unknown ?id= is a 404 instead of a blank page or a crash
    book_id = request.args.get("id", type=int)
    if book_id is None:
        abort(404)
    return db.get_or_404(Book, book_id)


def error_response(message):
    return jsonify({"status": "error", "message": message})


def parse_page_num(value):
    """Return (page_num, error). Anything that isn't a positive whole number is an error."""
    try:
        page_num = int(value)
    except (TypeError, ValueError):
        return None, "Page number must be a whole number"
    if page_num < 1:
        return None, "Page number must be at least 1"
    return page_num, None


@app.route('/')
def home():
    page_title = "Tanzim's Virtual Bookshelf"
    all_books = Book.query.order_by(Book.id.asc()).all()
    return render_template("index.html", page_title=page_title, books=all_books,
                           logged_in=current_user.is_authenticated)


@app.route('/about')
def about():
    page_title = "About Me"
    return render_template("about.html", page_title=page_title)


@app.route('/book_review')
def book_review():
    page_title = "Book Review"
    book_selected = get_book_or_404()
    return render_template("review.html", book=book_selected, page_title=page_title)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username") or ""
        password = request.form.get("password") or ""
        remember = request.form.get("rememberMe") == "on"  # Set remember based on checkbox

        user = User.query.filter_by(username=username).first()
        # One message for both cases so the form doesn't reveal which usernames exist
        if user and verify_password(user, password):
            if is_legacy_hash(user.password):
                # Upgrade a plain-text password to a hash the first time it is used
                user.password = generate_password_hash(password, method='pbkdf2:sha256')
                db.session.commit()
            login_user(user, remember=remember)
            return redirect(url_for("home"))
        flash("Invalid username or password", "error")

    return render_template("login.html", logged_in=current_user.is_authenticated)


@app.route('/change_password', methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        retype_password = request.form.get("retype_password") or ""

        if not verify_password(current_user, current_password):
            return error_response("Current password is incorrect")
        if len(new_password) < 8:
            return error_response("Password should be at least 8 characters long")
        if new_password != retype_password:
            return error_response("Passwords don't match. Try again!")

        current_user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        return jsonify({"status": "success", "message": "Password updated successfully!"})

    return render_template("change_password.html", username=current_user.username,
                           logged_in=current_user.is_authenticated)


def escape_like(text):
    # Treat % and _ typed in the search box as plain characters, not SQL wildcards
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    books = Book.query.filter(Book.title.ilike(f'%{escape_like(query)}%', escape='\\')) \
        .order_by(Book.id.asc()).all()
    return render_template("search_results.html", books=books, query=query)


@app.route('/dashboard')
@login_required
def dashboard():
    all_books = Book.query.order_by(Book.id.asc()).all()
    current_username = current_user.username
    return render_template("dashboard.html", books=all_books, username=current_username,
                           logged_in=current_user.is_authenticated)


@app.route('/view_all_books')
@login_required
def view_all_books():
    current_username = current_user.username
    all_books = Book.query.order_by(Book.id.asc()).all()
    return render_template("view_all_books.html", books=all_books, username=current_username,
                           logged_in=current_user.is_authenticated)


def export_rows():
    """All books as rows of plain values, in the same order as the site (oldest first)."""
    def safe(value):
        # Stops a cell like "=SUM(...)" from being run as a formula when opened in Excel
        if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')):
            return "'" + value
        return value

    books = Book.query.order_by(Book.id.asc()).all()
    return [[safe(v) for v in (b.title, b.author_name, b.genre, b.language, b.page_num,
                               b.read_unread, b.review, b.img_url)] for b in books]


EXPORT_HEADERS = ["Title", "Author Name", "Genre", "Language", "Pages", "Read?", "Review", "Image URL"]


@app.route('/export/csv')
@login_required
def export_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    writer.writerows(export_rows())
    # The BOM makes Excel read the file as UTF-8, so Bengali text isn't garbled
    data = '\ufeff' + buffer.getvalue()
    filename = f"books-{date.today().isoformat()}.csv"
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.route('/export/xlsx')
@login_required
def export_xlsx():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Books"
    sheet.append(EXPORT_HEADERS)
    for row in export_rows():
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for column, width in zip("ABCDEFGH", (40, 30, 40, 12, 8, 8, 50, 50)):
        sheet.column_dimensions[column].width = width

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"books-{date.today().isoformat()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route('/add_book', methods=["GET", "POST"])
@login_required
def add_book():
    current_username = current_user.username
    if request.method == "POST":
        # Get form data
        title = (request.form.get("title") or "").strip()
        author_name = (request.form.get("author_name") or "").strip()
        genre = [g.strip() for g in request.form.getlist("genre") if g.strip()]  # checkbox input -> getlist
        custom_genre = (request.form.get("custom_genre") or "").strip()  # Get custom genre if provided
        language = (request.form.get("language") or "").strip()
        page_num = request.form.get("page_num")
        read_unread = request.form.get("read_unread")
        review = (request.form.get("review") or "").strip()
        img_url = (request.form.get("img_url") or "").strip()

        # Check if custom genre is provided, if yes, use it instead of genre checkboxes
        if custom_genre:
            genre = [custom_genre]
        elif not genre:
            # If no custom genre, ensure at least one genre is selected
            return error_response("Please select at least one genre")

        # Perform validation
        if not all([title, author_name, page_num, language, read_unread]):
            return error_response("Please fill in all mandatory fields")
        page_num, page_error = parse_page_num(page_num)
        if page_error:
            return error_response(page_error)
        if title_taken(title):
            return error_response("A book with this title already exists")

        # Insert into database
        new_book = Book(
            title=title,
            author_name=author_name,
            genre=', '.join(genre),  # Convert genre list to comma-separated string
            language=language,
            page_num=page_num,
            read_unread=read_unread,
            review=review,
            img_url=img_url or None
        )
        db.session.add(new_book)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return error_response("A book with this title already exists")

        message = "Book added successfully!"
        cover_file = request.files.get("cover")
        if cover_file and cover_file.filename and not save_cover_upload(cover_file, title):
            message += " (The cover image was not saved: use a .jpg, .png, .webp or .gif file.)"
        return jsonify({"status": "success", "message": message})

    unique_genres = get_unique_genres()

    return render_template("add_book.html", unique_genres=unique_genres, username=current_username,
                           logged_in=current_user.is_authenticated)


@app.route("/update_book_info", methods=["GET", "POST"])
@login_required
def update_book_info():
    current_username = current_user.username
    book_selected = get_book_or_404()

    if request.method == "POST":
        # Get form data
        title = (request.form.get("title") or "").strip()
        author_name = (request.form.get("author_name") or "").strip()
        genre = [g.strip() for g in request.form.getlist("genre") if g.strip()]
        language = (request.form.get("language") or "").strip()
        page_num = request.form.get("page_num")
        read_unread = request.form.get("read_unread")
        review = request.form.get("review")
        img_url = request.form.get("img_url")
        old_title = book_selected.title

        if page_num:
            page_num, page_error = parse_page_num(page_num)
            if page_error:
                return error_response(page_error)
        if title and title != old_title and title_taken(title, exclude_id=book_selected.id):
            return error_response("A book with this title already exists")

        if title:
            book_selected.title = title
        if author_name:
            book_selected.author_name = author_name
        if genre:
            book_selected.genre = ', '.join(genre)
        if language:
            book_selected.language = language
        if page_num:
            book_selected.page_num = page_num
        if read_unread:
            book_selected.read_unread = read_unread
        if review is not None:
            book_selected.review = review.strip()  # An empty review clears it
        if img_url is not None:
            book_selected.img_url = img_url.strip() or None

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return error_response("A book with this title already exists")

        # Cover files are only touched after the database change succeeded
        message = "Book updated successfully!"
        new_title = book_selected.title
        title_changed = slugify(old_title) != slugify(new_title)
        cover_file = request.files.get("cover")
        try:
            if cover_file and cover_file.filename:
                old_cover = find_local_cover(old_title)
                if title_changed and old_cover:
                    # Drop the cover saved under the old title so it isn't orphaned
                    os.remove(os.path.join(COVERS_DIR, old_cover))
                if not save_cover_upload(cover_file, new_title):
                    message += " (The cover image was not saved: use a .jpg, .png, .webp or .gif file.)"
            elif title_changed:
                # Title changed without a new upload: rename the existing cover to follow the book
                old_cover = find_local_cover(old_title)
                if old_cover and not find_local_cover(new_title):
                    ext = os.path.splitext(old_cover)[1]
                    os.rename(os.path.join(COVERS_DIR, old_cover),
                              os.path.join(COVERS_DIR, slugify(new_title) + ext))
        except OSError:
            message += " (The cover file could not be updated.)"
        refresh_cover_index()

        # Return a JSON response indicating success
        return jsonify({"status": "success", "message": message})

    unique_genres = get_unique_genres()
    return render_template("update_book_info.html", book=book_selected,
                           username=current_username, unique_genres=unique_genres,
                           selected_genres={g.lower() for g in book_selected.genre_list},
                           logged_in=current_user.is_authenticated)


@app.route("/update_book")
@login_required
def update_book():
    current_username = current_user.username
    all_books = Book.query.order_by(Book.id.asc()).all()
    return render_template("update_book.html", books=all_books,
                           username=current_username, logged_in=current_user.is_authenticated)


# Deleting changes data, so it only accepts POST (a link or image on another site can't trigger it)
@app.route("/delete", methods=["POST"])
@login_required
def delete():
    book_to_delete = get_book_or_404()
    db.session.delete(book_to_delete)
    db.session.commit()
    return redirect(url_for("home"))


@app.route("/delete_book", methods=["POST"])
@login_required
def delete_book():
    book_to_delete = get_book_or_404()
    db.session.delete(book_to_delete)
    db.session.commit()
    return redirect(url_for("update_book"))


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0')
