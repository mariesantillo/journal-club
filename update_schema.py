from app import app, db
from sqlalchemy import Table, text

def main():
    with app.app_context():
        # Reflect the existing database
        metadata = db.MetaData()
        metadata.reflect(bind=db.engine)

        # Get the 'user' table
        user_table = Table('user', metadata, autoload_with=db.engine)

        # Check if the column exists
        if 'reminders' not in user_table.columns:
            # Add the new column if it doesn't exist
            with db.engine.connect() as connection:
                connection.execute(text('ALTER TABLE user ADD COLUMN reminders TEXT'))
                print("Column 'reminders' added successfully.")
        else:
            print("Column 'reminders' already exists.")

if __name__ == '__main__':
    main()
