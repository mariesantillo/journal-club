import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance/journal_club.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads/'
    
    # Flask-Mail configuration
    MAIL_SERVER = 'smtp.sendgrid.net'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'apikey'  # This is the string 'apikey', not an actual username
    MAIL_PASSWORD = 'your_sendgrid_api_key'
    MAIL_DEFAULT_SENDER = 'your_email@example.com'

const firebaseConfig = {
  apiKey: "AIzaSyBpxAAx4MYcLbB-7mJn3SX68jC4Ds9pbUc",
  authDomain: "journalclub-6a9bb.firebaseapp.com",
  projectId: "journalclub-6a9bb",
  storageBucket: "journalclub-6a9bb.appspot.com",
  messagingSenderId: "203269746887",
  appId: "1:203269746887:web:1c6f16f0ecd957eaa44ee2",
  measurementId: "G-B43L2TD46Y"
};