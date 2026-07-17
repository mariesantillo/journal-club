# config.py

import os
import json
from firebase_admin import credentials, firestore, initialize_app, storage

# -----------------------------------------------------------------------------
# Flask Configuration
# -----------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
UPLOAD_FOLDER = "static/uploads"

# -----------------------------------------------------------------------------
# Firebase
# -----------------------------------------------------------------------------

firebase_json = os.getenv("FIREBASE_CREDENTIALS")

if not firebase_json:
    raise RuntimeError(
        "FIREBASE_CREDENTIALS environment variable is missing."
    )

cred_dict = json.loads(firebase_json)

# Prevent Firebase being initialized twice
try:
    initialize_app(
        credentials.Certificate(cred_dict),
        {
            "storageBucket": "journalclub-6a9bb.appspot.com"
        },
    )
except ValueError:
    # already initialized
    pass

db = firestore.client()
bucket = storage.bucket()

# -----------------------------------------------------------------------------
# Site Settings
# -----------------------------------------------------------------------------

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

EMOJI_LIST = [
    "🦕",
    "🐹",
    "🐰",
    "🦊",
    "🐼",
    "🐷",
    "🐨",
    "🐝",
    "🐞",
    "🐥",
    "🐙",
    "🦭",
    "🦦",
    "🦔",
    "🐧",
    "🐯",
    "🫎",
    "🐢",
    "🐳",
    "🐮"
    "🐻‍❄️"
    "🐱"
    "🐻"
    "🦁"
    "🐴"
    "🦄"
    "🦋"
    "🐞"
    "🦎"
    "🦖"
    "🐡"
    "🦈"
    "🦚"
    "🦜"
]

MAX_JOKERS_PER_YEAR = 4