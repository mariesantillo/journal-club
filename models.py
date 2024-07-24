from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=False)
    receive_club_reminder = db.Column(db.Boolean(), nullable=True)
    receive_vote_reminder = db.Column(db.Boolean(), nullable=True)
    receive_upload_reminder = db.Column(db.Boolean(), nullable=True)

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id', name='fk_vote_article'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_vote_user'), nullable=False)
    article = db.relationship('Article', backref=db.backref('votes', lazy=True))
    user = db.relationship('User', backref=db.backref('votes', lazy=True))
