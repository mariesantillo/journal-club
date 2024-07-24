from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///journal_club.db'
app.config['UPLOAD_FOLDER'] = 'uploads/'

db = SQLAlchemy(app)

class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if request.method == 'POST':
        email = request.form['email']
        if not Member.query.filter_by(email=email).first():
            new_member = Member(email=email)
            db.session.add(new_member)
            db.session.commit()
            flash('Subscribed successfully!', 'success')
        else:
            flash('You are already subscribed!', 'warning')
        return redirect(url_for('home'))
    return render_template('subscribe.html')

@app.route('/upload', methods=['GET', 'POST'])
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
def vote():
    articles = Article.query.all()
    if request.method == 'POST':
        article_id = request.form['article']
        new_vote = Vote(article_id=article_id)
        db.session.add(new_vote)
        db.session.commit()
        flash('Voted successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('vote.html', articles=articles)

if __name__ == '__main__':
    app.run(debug=True)
