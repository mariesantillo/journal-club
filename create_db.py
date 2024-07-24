import os
from app import app, db

def create_db():
    with app.app_context():
        # Create the database and tables
        db.create_all()
        print("Database and tables created successfully.")

if __name__ == "__main__":
    create_db()
