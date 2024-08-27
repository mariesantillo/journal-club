from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from firebase_admin import credentials, firestore, initialize_app, storage
from wtforms import StringField, PasswordField, BooleanField, FileField, SubmitField
from wtforms.validators import InputRequired, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
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

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = UploadForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = file.filename

        # Save file locally to UPLOAD_FOLDER
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Upload the file to Firebase Storage
        blob = bucket.blob(f'pdfs/{filename}')
        blob.upload_from_filename(file_path)

        # Make the file publicly accessible
        blob.make_public()

        # Generate a public URL for the uploaded file
        download_url = blob.public_url

        # Save article data to Firestore
        article_data = {
            'title': form.title.data,
            'file_url': download_url,  # Store the download URL in Firestore
            'votes': 0,
            'emoji_votes': '',
            'user_id': current_user.id,
            'uploaded_by': current_user.username
        }

        article_ref = db.collection('articles').document()
        article_ref.set(article_data)
        flash('Article uploaded successfully!')

    articles = db.collection('articles').stream()
    articles_list = [{'id': article.id, **article.to_dict()} for article in articles]
    return render_template('dashboard.html', form=form, articles=articles_list)

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

@app.route('/meetings')
@login_required
def meetings():
    # Fetch meetings from the database (Firestore)
    meetings_ref = db.collection('meetings').stream()
    meetings_list = [{'id': meeting.id, **meeting.to_dict()} for meeting in meetings_ref]
    
    return render_template('meetings.html', meetings=meetings_list)

@app.route('/delete_article/<article_id>', methods=['POST'])
@login_required
def delete_article(article_id):
    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()
    if article.exists:
        article_data = article.to_dict()
        if article_data['user_id'] == current_user.id:
            # Delete file from Firebase Storage
            blob = bucket.blob(f"pdfs/{article_data['file_url'].split('/')[-1]}")
            blob.delete()

            # Delete article data from Firestore
            article_ref.delete()
            flash('Article deleted successfully!')
        else:
            flash('You are not authorized to delete this article.')
    else:
        flash('Article not found.')
    return redirect(url_for('dashboard'))

@app.route('/vote/<article_id>')
@login_required
def vote(article_id):
    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()
    if article.exists:
        article_data = article.to_dict()
        if current_user.emoji not in article_data['emoji_votes']:
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

if __name__ == '__main__':
    app.run(debug=True)
