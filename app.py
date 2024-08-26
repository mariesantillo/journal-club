from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from firebase_admin import credentials, firestore, initialize_app
from flask_migrate import Migrate  
from wtforms import StringField, PasswordField, BooleanField, FileField, SubmitField
from wtforms.validators import InputRequired, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
import os
import os
import random 

# Ensure this line is added to set the environment variable within your application
os.environ['FIREBASE_CREDENTIALS_PATH'] = '/Users/mariefrancine/Desktop/journal_club/secrets/journalclub-6a9bb-firebase-adminsdk-vqslj-2958062728.json'

firebase_cred_path = os.getenv('FIREBASE_CREDENTIALS_PATH')

if firebase_cred_path:
    cred = credentials.Certificate(firebase_cred_path)
    initialize_app(cred)
else:
    print("Firebase credentials path not set. Please set the FIREBASE_CREDENTIALS_PATH environment variable.")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'thisisasecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

EMOJI_LIST = ['🦕', '🐹', '🐰', '🦊', '🐼', '🐷', '🐨', '🐝', '🐞', '🐥', '🐙', '🦭', '🦦', '🦔', '🐧', '🐯', '🫎', '🐢', '🐳', '🐮']  # Define a list of emojis

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    emoji = db.Column(db.String(20))  # New column to store user's emoji

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    file_path = db.Column(db.String(150), nullable=False)
    votes = db.Column(db.Integer, default=0)
    emoji_votes = db.Column(db.String, default='')  # New column to store emojis of voters
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class SettingsForm(FlaskForm):
    # email_reminders = BooleanField('Receive email reminders for upcoming meetings')
    # email_new_articles = BooleanField('Receive notifications for new articles')
    # email_vote_results = BooleanField('Receive notifications when an article wins')
    submit = SubmitField('Save Changes')

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])
    remember = BooleanField('Remember me')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])

    def validate_username(self, username):
        existing_user = User.query.filter_by(username=username.data).first()
        if existing_user:
            raise ValidationError('That username is taken. Please choose a different one.')

class UploadForm(FlaskForm):
    title = StringField('Article Title', validators=[InputRequired()])
    file = FileField('Upload Article', validators=[InputRequired()])
    submit = SubmitField('Upload')

@app.route('/')
def index():
    articles = Article.query.all()
    return render_template('index.html', articles=articles)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect(url_for('dashboard'))

        flash('Invalid username or password')

    return render_template('login.html', form=form)

@app.route('/user')
@login_required
def user():
    articles = Article.query.filter_by(user_id=current_user.id).all()
    return render_template('user.html', articles=articles)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        # Assign a random emoji from the list
        assigned_emoji = random.choice(EMOJI_LIST)
        new_user = User(username=form.username.data, password=hashed_password, emoji=assigned_emoji)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! You can now log in.')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = UploadForm()
    if form.validate_on_submit():
        file = form.file.data
        upload_folder = app.config['UPLOAD_FOLDER']

        # Ensure the upload directory exists
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        file_path = os.path.join(upload_folder, file.filename)
        file.save(file_path)

        new_article = Article(title=form.title.data, file_path=file_path, user_id=current_user.id)
        db.session.add(new_article)
        db.session.commit()
        flash('Article uploaded successfully!')

    articles = Article.query.all()
    return render_template('dashboard.html', form=form, articles=articles)

@app.route('/vote/<int:article_id>')
@login_required
def vote(article_id):
    article = Article.query.get_or_404(article_id)
    
    # Check if the current user's emoji is already in the vote list to prevent duplicate voting
    if current_user.emoji not in article.emoji_votes:
        article.votes += 1
        article.emoji_votes += current_user.emoji  # Add user's emoji to the vote list
        db.session.commit()
        flash('Vote cast successfully!')
    else:
        flash('You have already voted for this article!')

    return redirect(url_for('index'))


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
        # Update the user without the email fields
        db.session.commit()
        flash('Settings updated successfully!')
        return redirect(url_for('settings'))
    return render_template('settings.html', form=form)



if __name__ == '__main__':
    app.run(debug=True)
