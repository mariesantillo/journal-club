from app import app, db
from app import User

def check_users():
    with app.app_context():
        users = User.query.all()
        for user in users:
            print(f"Email: {user.email}, Password Hash: {user.password}")

if __name__ == "__main__":
    check_users()
