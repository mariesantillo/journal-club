# config.py

import os
import json
import cloudinary
from firebase_admin import credentials, firestore, initialize_app

# -----------------------------------------------------------------------------
# Flask Configuration
# -----------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
UPLOAD_FOLDER = "static/uploads"

# -----------------------------------------------------------------------------
# Firebase (Firestore database only — file storage has moved to Cloudinary,
# see below, since Cloud Storage for Firebase now requires the Blaze plan)
# -----------------------------------------------------------------------------

firebase_json = os.getenv("FIREBASE_CREDENTIALS")

if not firebase_json:
    raise RuntimeError(
        "FIREBASE_CREDENTIALS environment variable is missing."
    )

cred_dict = json.loads(firebase_json)

# Prevent Firebase being initialized twice
try:
    initialize_app(credentials.Certificate(cred_dict))
except ValueError:
    # already initialized
    pass

db = firestore.client()

# -----------------------------------------------------------------------------
# Cloudinary (PDF storage — free plan, no credit card required)
# -----------------------------------------------------------------------------

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    raise RuntimeError(
        "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET "
        "environment variables are required."
    )

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

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
    "🐮",
    "🐻‍❄️",
    "🐱",
    "🐻",
    "🦁",
    "🐴",
    "🦄",
    "🦋",
    "🦎",
    "🦖",
    "🐡",
    "🦈",
    "🦚",
    "🦜",
]

MAX_JOKERS_PER_YEAR = 4