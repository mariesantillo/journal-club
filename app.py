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
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'thisisasecretkey'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

bucket = storage.bucket()

# Load Firebase credentials from environment variable
firebase_cred_json = os.getenv('FIREBASE_CREDENTIALS')

if firebase_cred_json:
    cred_dict = json.loads(firebase_cred_json)
    cred = credentials.Certificate(cred_dict)
    initialize_app(cred)
    db = firestore.client()  # Initialize Firestore client
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

def convert_firestore_timestamp(timestamp):
    return timestamp.to_datetime() if timestamp else None

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
    articles = db.collection('articles').stream()
    articles_list = [{'id': article.id, **article.to_dict()} for article in articles]
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
            else:
                flash('Invalid password')
        else:
            flash('Invalid username')
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
            return redirect(url_for('login'))  # Redirect to login page after registration
    return render_template('register.html', form=form)

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = UploadForm()
    if form.validate_on_submit():
        file = form.file.data
        blob = bucket.blob(f"uploads/{file.filename}")  # Create a blob in Firebase Storage
        blob.upload_from_file(file)  # Upload the file
        blob.make_public()  # Make the file publicly accessible

        # Create a document in the 'articles' collection
        article_data = {
            'title': form.title.data,
            'file_url': blob.public_url,  # Store the public URL
            'votes': 0,
            'emoji_votes': '',
            'user_id': current_user.id,
            'uploaded_at': firestore.SERVER_TIMESTAMP  # Add a timestamp
        }

        article_ref = db.collection('articles').document()  # Create a new document
        article_ref.set(article_data)  # Set the document with article data
        flash('Article uploaded successfully!')

    articles = db.collection('articles').stream()
    articles_list = [{'id': article.id, **article.to_dict()} for article in articles]
    return render_template('dashboard.html', form=form, articles=articles_list)

@app.route('/vote/<article_id>')
@login_required
def vote(article_id):
    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()
    if article.exists:
        article_data = article.to_dict()
        if current_user.emoji not in article_data.get('emoji_votes', ''):
            article_data['votes'] += 1
            article_data['emoji_votes'] += current_user.emoji
            article_ref.update(article_data)
            flash('Vote cast successfully!')
        else:
            flash('You have already voted for this article!')
    else:
        flash('Article not found.')
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm(obj=current_user)
    if form.validate_on_submit():
        flash('Settings updated successfully!')
        return redirect(url_for('settings'))
    return render_template('settings.html', form=form)

@app.route('/meetings')
@login_required
def meetings():
    meetings_ref = db.collection('meetings').order_by('meeting_date').stream()
    meetings_list = [
        {
            'id': meeting.id,
            'meeting_date': convert_firestore_timestamp(meeting.to_dict().get('meeting_date')),
            'submission_deadline': convert_firestore_timestamp(meeting.to_dict().get('submission_deadline')),
            'voting_deadline': convert_firestore_timestamp(meeting.to_dict().get('voting_deadline'))
        }
        for meeting in meetings_ref
    ]
    return render_template('meetings.html', meetings=meetings_list)

@app.route('/add_meeting', methods=['GET', 'POST'])
@login_required  # Ensure only logged-in users can access this route
def add_meeting():
    if not current_user.is_authenticated:
        flash('You need to be logged in to add a meeting!')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        meeting_date = request.form.get('meeting_date')
        submission_deadline = request.form.get('submission_deadline')
        voting_deadline = request.form.get('voting_deadline')

        # Convert string dates to Firestore Timestamps
        meeting_data = {
            'meeting_date': firestore.Timestamp.fromisoformat(meeting_date),
            'submission_deadline': firestore.Timestamp.fromisoformat(submission_deadline),
            'voting_deadline': firestore.Timestamp.fromisoformat(voting_deadline)
        }

        # Add a new document to the 'meetings' collection
        meeting_ref = db.collection('meetings').document()
        meeting_ref.set(meeting_data)
        flash('Meeting added successfully!')

    return render_template('add_meeting.html')


if __name__ == '__main__':
    app.run(debug=True)
