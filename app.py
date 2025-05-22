from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from firebase_admin import credentials, firestore, initialize_app, storage
from wtforms import StringField, PasswordField, BooleanField, FileField, SubmitField
from wtforms.validators import InputRequired, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import json
import uuid
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'thisisasecretkey'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Load Firebase credentials from environment variable
firebase_cred_json = os.getenv('FIREBASE_CREDENTIALS')

if firebase_cred_json:
    cred_dict = json.loads(firebase_cred_json)
    cred = credentials.Certificate(cred_dict)
    initialize_app(cred, {'storageBucket': 'journalclub-6a9bb.appspot.com'})  # Make sure to replace with your bucket name
    db = firestore.client()  # Initialize Firestore client
    bucket = storage.bucket()  # Initialize Firebase Storage bucket
else:
    print("Firebase credentials not set. Please set the FIREBASE_CREDENTIALS environment variable.")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

EMOJI_LIST = ['🦕', '🐹', '🐰', '🦊', '🐼', '🐷', '🐨', '🐝', '🐞', '🐥', '🐙', '🦭', '🦦', '🦔', '🐧', '🐯', '🫎', '🐢', '🐳', '🐮']

class User(UserMixin):
    def __init__(self, user_id, username, password, emoji):
        self.id = user_id
        self.username = username
        self.password = password
        self.emoji = emoji

class SettingsForm(FlaskForm):
    submit = SubmitField('Save Changes')

@login_manager.user_loader
def load_user(user_id):
    user_ref = db.collection('users').document(user_id).get()
    if user_ref.exists:
        user_data = user_ref.to_dict()
        return User(user_id=user_id, username=user_data['username'], password=user_data['password'], emoji=user_data['emoji'])
    return None

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])
    remember = BooleanField('Remember me')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])

    def validate_username(self, username):
        user_ref = db.collection('users').document(username.data).get()
        if user_ref.exists:
            raise ValidationError('That username is taken. Please choose a different one.')

class UploadForm(FlaskForm):
    title = StringField('Article Title', validators=[InputRequired()])
    file = FileField('Upload Article', validators=[InputRequired()])
    submit = SubmitField('Upload')

@app.route('/')
def index():
    articles = db.collection('articles').where('voting_month', '==', datetime.now().strftime('%Y-%m')).stream()
    articles_list = [{'id': a.id, **a.to_dict()} for a in articles]
    return render_template('index.html', articles=articles_list)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user_ref = db.collection('users').document(form.username.data).get()
        if user_ref.exists:
            user_data = user_ref.to_dict()
            user = User(user_id=form.username.data, username=user_data['username'], password=user_data['password'], emoji=user_data['emoji'])
            if check_password_hash(user.password, form.password.data):
                login_user(user, remember=form.remember.data)
                return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html', form=form)

@app.route('/user')
@login_required
def user():
    articles = db.collection('articles').where('user_id', '==', current_user.id).stream()
    articles_list = [{'id': article.id, **article.to_dict()} for article in articles]
    return render_template('user.html', articles=articles_list)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        assigned_emoji = random.choice(EMOJI_LIST)
        user_data = {
            'username': form.username.data,
            'password': hashed_password,
            'emoji': assigned_emoji
        }
        user_ref = db.collection('users').document(form.username.data)
        if user_ref.get().exists:
            flash('Username already taken. Please choose a different one.')
        else:
            user_ref.set(user_data)
            flash('Registration successful! You can now log in.')
            return redirect(url_for('login'))
    return render_template('register.html', form=form)

from datetime import datetime

from datetime import datetime, timedelta

@app.route('/delete_article/<article_id>', methods=['POST'])
@login_required
def delete_article(article_id):
    # Get the next parameter from the request to determine where to redirect
    next_page = request.args.get('next', 'dashboard')  # Default to 'dashboard' if not specified

    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()
    
    if article.exists:
        article_data = article.to_dict()
        if article_data['user_id'] == current_user.id:
            if 'file_url' in article_data and article_data['file_url']:
                try:
                    # Extract filename from file_url
                    filename = article_data['file_url'].split('/')[-1]

                    # Delete file from Firebase Storage
                    blob = bucket.blob(f"pdfs/{filename}")
                    blob.delete()
                except Exception as e:
                    flash(f"Error deleting file from storage: {str(e)}")
            else:
                flash('No file associated with this article.')

            # Delete article data from Firestore
            article_ref.delete()
            flash('Article deleted successfully!')
        else:
            flash('You are not authorized to delete this article.')
    else:
        flash('Article not found.')

    # Redirect based on the 'next' parameter
    if next_page == 'user':
        return redirect(url_for('user'))
    else:
        return redirect(url_for('dashboard'))

from flask import session, jsonify

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = UploadForm()

    today = datetime.now()
    if today.month == 12:
        next_month = datetime(today.year + 1, 1, 1)
    else:
        next_month = datetime(today.year, today.month + 1, 1)

    if form.validate_on_submit():
        try:
            # File upload logic
            file = form.file.data
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)

            # Upload the file to Firebase Storage and get the download URL
            storage_path = f'pdfs/{file.filename}'
            bucket.blob(storage_path).upload_from_filename(file_path)
            file_url = f'https://storage.googleapis.com/{bucket.name}/{storage_path}'

            # Add article to Firestore
            article_data = {
                'title': form.title.data,
                'file_url': file_url,
                'votes': 0,
                'emoji_votes': '',
                'user_id': current_user.id,
                'user_name': current_user.username,
                'voting_month': datetime.now().strftime('%Y-%m'),
                'submission_deadline': datetime.now() + timedelta(days=7),  # Example dates
                'voting_deadline': datetime.now() + timedelta(days=14)
            }
            db.collection('articles').add(article_data)
            flash('Article uploaded successfully!')
            return redirect(url_for('dashboard'))

        except Exception as e:
            flash(f"An error occurred during the upload: {str(e)}")
            print(f"Error during file upload: {str(e)}")  # Debugging statement

    try:
        # Get the upcoming meeting dates
        submission_deadline, voting_deadline = get_upcoming_meeting_dates()

        if submission_deadline and voting_deadline:
            # Only show articles that are within the current voting period
            current_month = datetime.now().strftime('%Y-%m')
            print(f"Current Month: {current_month}")
            print(f"Submission Deadline: {submission_deadline}")
            print(f"Voting Deadline: {voting_deadline}")

            # Fetch articles that are within the submission and voting deadlines
            articles_query = db.collection('articles').filter(
                'voting_month', '==', current_month
            ).filter(
                'submission_deadline', '>=', datetime.now()
            ).filter(
                'voting_deadline', '>=', datetime.now()
            )
            articles = articles_query.stream()

            # Convert Firestore documents to a list
            articles_list = [{'id': a.id, **a.to_dict()} for a in articles]

            # ✅ Sort by vote count descending
            articles_list.sort(key=lambda a: a.get('votes', 0), reverse=True)

            print(f"Fetched Articles: {articles_list}")
        else:
            articles_list = []
            flash('No upcoming meeting found. Please add the dates for the next meeting!')

    except Exception as e:
        print(f"Error fetching articles: {e}")  # Debugging output
        flash(f"An error occurred while fetching articles: {e}")
        articles_list = []

    return render_template('dashboard.html', form=form, articles=articles_list, voting_month_name=next_month.strftime('%B'))

@app.route('/article/<article_id>')
@login_required
def view_article(article_id):
    article_ref = db.collection('articles').document(article_id).get()
    if article_ref.exists:
        article_data = article_ref.to_dict()
        
        # Check if the article has a PDF file associated with it
        pdf_url = article_data.get('file_url', None)
        
        # Render the article page with an embedded PDF viewer and download link
        return render_template('view_article.html', article=article_data, pdf_url=pdf_url)
    else:
        flash('Article not found.')
        return redirect(url_for('dashboard'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = UploadForm()

    if form.validate_on_submit():
        file = form.file.data
        filename = file.filename

        # Check file extension
        if not filename.lower().endswith('.pdf'):
            flash('Only PDF files are allowed.')
            return redirect(url_for('upload'))

        # Create a unique filename
        unique_filename = f"{uuid.uuid4().hex}_{filename}"

        # Ensure the upload directory exists
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)

        # Save locally
        local_path = os.path.join(upload_folder, unique_filename)
        file.save(local_path)

        submission_deadline, voting_deadline = get_upcoming_meeting_dates()

        # Fallback if no upcoming meeting is set
        if not submission_deadline:
            submission_deadline = datetime.now() + timedelta(days=7)
        if not voting_deadline:
            voting_deadline = datetime.now() + timedelta(days=14)

        # Upload to Firebase Storage
        blob = bucket.blob(f'pdfs/{unique_filename}')
        blob.upload_from_filename(local_path)
        blob.make_public()
        file_url = blob.public_url

        now = datetime.now()
        article_data = {
            'title': form.title.data,
            'file_url': file_url,
            'votes': 0,
            'emoji_votes': {},
            'emoji': current_user.emoji,
            'user_id': current_user.id,
            'user_name': current_user.username,
            'created_at': datetime.now(),
            'voting_month': datetime.now().strftime('%Y-%m'),
            'voted_users': [],
            'submission_deadline': submission_deadline,
            'voting_deadline': voting_deadline
        }

        db.collection('articles').add(article_data)
        flash('Article uploaded successfully!')
        return redirect(url_for('dashboard'))

    # Fetch uploaded articles by current user
    user_articles = db.collection('articles').where('user_id', '==', current_user.id).stream()
    articles_list = [{'id': a.id, **a.to_dict()} for a in user_articles]

    return render_template('upload_article.html', form=form, articles=articles_list)

def get_upcoming_meeting_dates():
    try:
        meetings_ref = db.collection('meetings')
        # Use the 'where' method with positional arguments
        upcoming_meeting = meetings_ref.order_by('meeting_date').where('meeting_date', '>=', datetime.now()).limit(1).stream()
        upcoming_meeting_data = list(upcoming_meeting)

        if upcoming_meeting_data:
            meeting = upcoming_meeting_data[0]
            submission_deadline = meeting.to_dict().get('submission_deadline')
            voting_deadline = meeting.to_dict().get('voting_deadline')
            return submission_deadline, voting_deadline
        else:
            print("No upcoming meetings found.")
            return None, None
    except Exception as e:
        print(f"Error fetching upcoming meeting dates: {str(e)}")
        return None, None

@app.route('/meetings')
@login_required
def meetings():
    # Fetch meetings from the database (Firestore)
    meetings_ref = db.collection('meetings').stream()
    meetings_list = [{'id': meeting.id, **meeting.to_dict()} for meeting in meetings_ref]
    
    return render_template('meetings.html', meetings=meetings_list)

@app.route('/vote/<article_id>/<emoji>')
@login_required
def emoji_vote(article_id, emoji):
    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()
    if article.exists:
        article_data = article.to_dict()
        current_month = datetime.now().strftime('%Y-%m')

        if article_data.get('voting_month') == current_month:
            if current_user.id in article_data.get('voted_users', []):
                flash("You’ve already voted.")
            else:
                article_ref.update({
                    'votes': firestore.Increment(1),
                    'voted_users': firestore.ArrayUnion([current_user.id]),
                    f'emoji_votes.{current_user.id}': current_user.emoji
                })
                flash(f"Vote cast sucessfully!")
        else:
            flash("Voting closed for this article.")
    else:
        flash("Article not found.")

    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/add_meeting', methods=['GET', 'POST'])
@login_required
def add_meeting():
    if request.method == 'POST':
        # Logic for adding a new meeting
        # Fetch data from the form, save to Firestore, etc.
        meeting_data = {
            'title': request.form['title'],
            'description': request.form['description'],
            'date': request.form['date'],
            # Add other fields as necessary
        }
        meetings_ref = db.collection('meetings').document()
        meetings_ref.set(meeting_data)
        flash('Meeting added successfully!')
        return redirect(url_for('meetings'))
    
    return render_template('add_meeting.html')  # Create this template for adding meetings

@app.route('/admin')
@login_required
def admin():
    if current_user.id != 'admin':
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    users = db.collection('users').stream()
    articles = db.collection('articles').stream()
    meetings = db.collection('meetings').stream()

    return render_template('admin_panel.html', users=[u.to_dict() for u in users],
                           articles=[{'id': a.id, **a.to_dict()} for a in articles],
                           meetings=[m.to_dict() for m in meetings])

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm(obj=current_user)
    if form.validate_on_submit():
        flash('Settings updated successfully!')
        return redirect(url_for('settings'))
    return render_template('settings.html', form=form)

if __name__ == '__main__':
    app.run(debug=True)
