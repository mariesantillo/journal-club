from app import app, db
from sqlalchemy import text

def update_schema():
    with app.app_context():
        db.engine.execute(text('ALTER TABLE vote ADD COLUMN user_id INTEGER'))
        print("Column 'user_id' added to 'vote' table successfully.")

if __name__ == "__main__":
    update_schema()

