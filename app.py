from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///journal_club.db'
app.config['UPLOAD_FOLDER'] = 'uploads/'

# Flask-Mail configuration
app.config['MAIL_SERVER'] = 'smtp.sendgrid.net'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'apikey'  # This is the string 'apikey', not an actual username
app.config['MAIL_PASSWORD'] = 'your_sendgrid_api_key'
app.config['MAIL_DEFAULT_SENDER'] = 'your_email@example.com'

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    articles = Article.query.all()
    return render_template('home.html', articles=articles)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='sha256')
        new_user = User(email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Login failed. Check your email and password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if request.method == 'POST':
        email = request.form['email']
        if not User.query.filter_by(email=email).first():
            new_user = User(email=email, password=generate_password_hash('defaultpassword', method='sha256'))
            db.session.add(new_user)
            db.session.commit()
            flash('Subscribed successfully!', 'success')
        else:
            flash('You are already subscribed!', 'warning')
        return redirect(url_for('home'))
    return render_template('subscribe.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        title = request.form['title']
        file = request.files['file']
        if file and title:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            new_article = Article(title=title, filename=filename)
            db.session.add(new_article)
            db.session.commit()
            flash('Article uploaded successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('upload.html')

@app.route('/vote/<int:article_id>', methods=['POST'])
@login_required
def vote(article_id):
    new_vote = Vote(article_id=article_id, user_id=current_user.id)
    db.session.add(new_vote)
    db.session.commit()
    flash('Voted successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/results')
def results():
    results = db.session.query(Article, db.func.count(Vote.id).label('vote_count'))\
                .outerjoin(Vote)\
                .group_by(Article.id)\
                .order_by(db.desc('vote_count'))\
                .all()
    return render_template('results.html', results=results)

def send_reminder_email():
    articles = db.session.query(Article, db.func.count(Vote.id).label('vote_count'))\
                .outerjoin(Vote)\
                .group_by(Article.id)\
                .order_by(db.desc('vote_count'))\
                .all()
    if articles:
        top_article = articles[0][0]
        recipients = [user.email for user in User.query.all()]
        with mail.connect() as conn:
            for recipient in recipients:
                message = f"Reminder: The journal club is tomorrow. The top article this week is '{top_article.title}'. Don't forget to read it!"
                msg = Message(subject="Journal Club Reminder",
                              recipients=[recipient],
                              body=message)
                conn.send(msg)

scheduler = BackgroundScheduler()
scheduler.add_job(func=send_reminder_email, trigger="cron", day_of_week='sun', hour=8)  # Example: run every Sunday at 8 AM
scheduler.start()

if __name__ == '__main__':
    app.run(debug=True)
