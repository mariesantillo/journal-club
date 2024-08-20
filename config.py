import os

class Config:
    # Flask-Mail configuration
    MAIL_SERVER = 'smtp.sendgrid.net'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'apikey'  # This is the string 'apikey', not an actual username
    MAIL_PASSWORD = 'your_sendgrid_api_key'  # Replace with your actual SendGrid API key
    MAIL_DEFAULT_SENDER = 'your_email@example.com'

    # Other configurations (if any)
    UPLOAD_FOLDER = 'uploads/'
