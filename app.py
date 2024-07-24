from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///journal_club.db'
app.config['UPLOAD_FOLDER'] = 'uploads/'

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

@app.route('/vote', methods=['GET', 'POST'])
@login_required
def vote():
    articles = Article.query.all()
    if request.method == 'POST':
        article_id = request.form['article']
        new_vote = Vote(article_id=article_id, user_id=current_user.id)
        db.session.add(new_vote)
        db.session.commit()
        flash('Voted successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('vote.html', articles=articles)

@app.route('/results')
def results():
    results = db.session.query(Article, db.func.count(Vote.id).label('vote_count'))\
                .outerjoin(Vote)\
                .group_by(Article.id)\
                .order_by(db.desc('vote_count'))\
                .all()
    return render_template('results.html', results=results)

if __name__ == '__main__':
    app.run(debug=True)
