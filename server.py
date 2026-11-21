import os
import re
import unicodedata
import requests
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

app = Flask(__name__)
csrf = CSRFProtect(app)

# Database Created
app.config['SECRET_KEY'] = os.environ.get('MY_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('MY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)

# Book cover images are stored as files in static/img/covers/, named after the book title
COVERS_DIR = os.path.join(app.static_folder, 'img', 'covers')
ALLOWED_COVER_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
_cover_index = None  # Cache of {slug: filename}, built on first use


def slugify(text):
    # Keeps letters/digits of any script (e.g. Bengali) and combining marks; everything else
    # (spaces, punctuation, apostrophes, zero-width joiners) becomes a single "-".
    text = unicodedata.normalize('NFC', (text or '').lower()).replace("'", '').replace('’', '')
    kept = ''.join(ch if unicodedata.category(ch)[0] in 'LMN' else '-' for ch in text)
    return re.sub(r'-+', '-', kept).strip('-')


def refresh_cover_index():
    global _cover_index
    _cover_index = {}
    if os.path.isdir(COVERS_DIR):
        for filename in os.listdir(COVERS_DIR):
            stem, ext = os.path.splitext(filename)
            if ext.lower() in ALLOWED_COVER_EXTENSIONS:
                _cover_index[slugify(stem)] = filename
    return _cover_index


def find_local_cover(title):
    index = _cover_index if _cover_index is not None else refresh_cover_index()
    return index.get(slugify(title))


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


# Function to fetch data from Sheety API and add new books to the database
def add_new_books_from_sheety():
    # Sheety API endpoint and bearer headers
    sheety_endpoint = os.environ.get('MY_SHEETY_ENDPOINT')
    bearer_headers = {
        "Authorization": os.environ.get('BEARER_TOKEN')
    }

    # Fetch data from Sheety API
    response = requests.get(url=sheety_endpoint, headers=bearer_headers)
    result = response.json()

    if "bookshelf" not in result:
        return  # No books found, return without adding anything

    # Get existing titles from the database
    existing_titles = [book.title for book in Book.query.all()]

    # Counter for new books added
    new_books_added = 0

    # Loop through each book from Sheety API
    for book_data in result["bookshelf"]:
        # Check if the book title is not already in the database
        if book_data["bookTitle"] not in existing_titles:
            # Create a new book object
            new_book = Book(
                title=book_data["bookTitle"],
                author_name=book_data["authorName"],
                genre=book_data["genre"],
                language=book_data["language"],
                page_num=book_data["pageNumber"],
                read_unread=book_data["read/Unread"],
                review=book_data["review"],
                img_url=book_data["imageLink"]
            )

            # Add the new book to the database
            with current_app.app_context():
                db.session.add(new_book)
                db.session.commit()

            # Increment the counter for new books added
            new_books_added += 1

    return new_books_added


def get_unique_genres():
    # Query all books from the database
    books = Book.query.all()

    genre_set = set()  # Use a set to store unique genres

    for book in books:
        # Split the genre string into individual genres
        genres = book.genre.split(', ')

        # Convert each genre to title case and add to the set
        for genre in genres:
            title_case_genre = genre.strip().title()  # Strip whitespace and convert to title case
            genre_set.add(title_case_genre)

    # Convert the set to a sorted list (optional, for consistent ordering)
    unique_genres = sorted(genre_set)

    return unique_genres


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
            return url_for('static', filename=f'img/covers/{filename}')
        return self.img_url

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
    all_books = Book.query.order_by(Book.id.asc()).all()
    book_id = request.args.get("id")
    book_selected = Book.query.get(book_id)
    return render_template("review.html", book=book_selected, books=all_books, page_title=page_title)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("rememberMe") == "on"  # Set remember based on checkbox

        user = User.query.filter_by(username=username).first()
        if user:
            if user.password == password:
                login_user(user, remember=remember)
                return redirect(url_for("home"))
            else:
                flash("Invalid password", "error")
        else:
            flash("User not found", "error")

    return render_template("login.html", logged_in=current_user.is_authenticated)


@app.route('/search', methods=["GET", "POST"])
def search():
    query = request.args.get('query', '')
    print("Received query:", query)
    # Perform search query using the 'query' parameter
    books = Book.query.filter(Book.title.ilike(f'%{query}%')).all()
    # Return JSON response with search results
    # return jsonify(results=[book.serialize() for book in books])
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


@app.route('/refresh_books')
@login_required
def refresh_books():
    # Call the function to add new books from Sheety API
    new_books_added = add_new_books_from_sheety()
    print(new_books_added)

    # Redirect back to the dashboard page
    return redirect(url_for('home'))


@app.route('/add_book', methods=["GET", "POST"])
@login_required
def add_book():
    current_username = current_user.username
    if request.method == "POST":
        # Get form data
        title = request.form.get("title")
        author_name = request.form.get("author_name")
        genre = request.form.getlist("genre")  # Since genre is checkbox input, use getlist
        custom_genre = request.form.get("custom_genre")  # Get custom genre if provided
        language = request.form.get("language")
        page_num = request.form.get("page_num")
        read_unread = request.form.get("read_unread")
        review = request.form.get("review")
        img_url = request.form.get("img_url")

        # Check if custom genre is provided, if yes, use it instead of genre checkboxes
        if custom_genre:
            genre = [custom_genre]
        else:
            # If no custom genre, ensure at least one genre is selected
            if not genre:
                return jsonify({"status": "error", "message": "Please select at least one genre"})

        # Perform validation
        if not all([title, author_name, page_num, language, read_unread]):
            return jsonify({"status": "error", "message": "Please fill in all mandatory fields"})

        # Insert into database
        new_book = Book(
            title=title,
            author_name=author_name,
            genre=', '.join(genre),  # Convert genre list to comma-separated string
            language=language,
            page_num=int(page_num),
            read_unread=read_unread,
            review=review,
            img_url=img_url
        )
        db.session.add(new_book)
        db.session.commit()
        save_cover_upload(request.files.get("cover"), title)
        return jsonify({"status": "success", "message": "Book added successfully!"})

    unique_genres = get_unique_genres()

    return render_template("add_book.html", unique_genres=unique_genres, username=current_username,
                           logged_in=current_user.is_authenticated)


@app.route("/update_book_info", methods=["GET", "POST"])
@login_required
def update_book_info():
    current_username = current_user.username
    all_books = Book.query.order_by(Book.id.asc()).all()
    book_id = request.args.get("id")
    book_selected = Book.query.get(book_id)
    unique_genres = get_unique_genres()

    if request.method == "POST":
        # Get form data
        title = request.form.get("title")
        author_name = request.form.get("author_name")
        genre = request.form.getlist("genre")  # Since genre is checkbox input, use getlist
        language = request.form.get("language")
        page_num = request.form.get("page_num")
        read_unread = request.form.get("read_unread")
        review = request.form.get("review")
        img_url = request.form.get("img_url")
        old_title = book_selected.title

        if title:
            book_selected.title = title
        if author_name:
            book_selected.author_name = author_name
        if genre:
            genre_str = ', '.join(genre)
            book_selected.genre = genre_str
        if language:
            book_selected.language = language
        if page_num:
            book_selected.page_num = int(page_num)
        if read_unread:
            book_selected.read_unread = read_unread
        if review:
            book_selected.review = review
        if img_url:
            book_selected.img_url = img_url

        cover_file = request.files.get("cover")
        if title and cover_file and cover_file.filename:
            # Title changed: drop the cover saved under the old title so it isn't orphaned
            old_cover = find_local_cover(old_title)
            if old_cover and slugify(old_title) != slugify(title):
                os.remove(os.path.join(COVERS_DIR, old_cover))
                refresh_cover_index()
        elif title and slugify(old_title) != slugify(title):
            # Title changed without a new upload: rename the existing cover to follow the book
            old_cover = find_local_cover(old_title)
            if old_cover and not find_local_cover(title):
                ext = os.path.splitext(old_cover)[1]
                os.rename(os.path.join(COVERS_DIR, old_cover),
                          os.path.join(COVERS_DIR, slugify(title) + ext))
                refresh_cover_index()
        save_cover_upload(cover_file, book_selected.title)

        db.session.commit()
        # Return a JSON response indicating success
        return jsonify({"status": "success", "message": "Book updated successfully!"})

    return render_template("update_book_info.html", book=book_selected, books=all_books,
                           username=current_username, unique_genres=unique_genres,
                           logged_in=current_user.is_authenticated)


@app.route("/update_book", methods=["GET", "POST"])
@login_required
def update_book():
    current_username = current_user.username
    all_books = Book.query.order_by(Book.id.asc()).all()
    return render_template("update_book.html", books=all_books,
                           username=current_username, logged_in=current_user.is_authenticated)


@app.route("/delete")
@login_required
def delete():
    book_id = request.args.get("id")

    # DELETE A RECORD BY ID
    book_to_delete = Book.query.get(book_id)
    db.session.delete(book_to_delete)
    db.session.commit()
    return redirect(url_for("home"))


@app.route("/delete_book")
@login_required
def delete_book():
    book_id = request.args.get("id")

    # DELETE A RECORD BY ID
    book_to_delete = Book.query.get(book_id)
    db.session.delete(book_to_delete)
    db.session.commit()
    return redirect(url_for("update_book"))


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0')
