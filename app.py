from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, FileField, SubmitField, SelectField
from wtforms.validators import InputRequired, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import uuid
import random
import os
import cloudinary.uploader

from config import (
    SECRET_KEY,
    UPLOAD_FOLDER,
    db,
    ADMIN_USERNAME,
    EMOJI_LIST,
    MAX_JOKERS_PER_YEAR,
)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, user_id, username, password, emoji, is_admin=False):
        self.id = user_id
        self.username = username
        self.password = password
        self.emoji = emoji
        self.is_admin = is_admin


class SettingsForm(FlaskForm):
    emoji = SelectField('Emoji Avatar', choices=[(e, e) for e in EMOJI_LIST])
    submit = SubmitField('Save Changes')


def _resolve_is_admin(user_id, user_data):
    # Accounts created before the multi-admin feature don't have an
    # `is_admin` field yet — fall back to the bootstrap ADMIN_USERNAME so
    # that account isn't accidentally locked out of the admin panel.
    return user_data.get('is_admin', user_id == ADMIN_USERNAME)


@login_manager.user_loader
def load_user(user_id):
    user_ref = db.collection('users').document(user_id).get()
    if user_ref.exists:
        user_data = user_ref.to_dict()
        return User(
            user_id=user_id,
            username=user_data['username'],
            password=user_data['password'],
            emoji=user_data['emoji'],
            is_admin=_resolve_is_admin(user_id, user_data),
        )
    return None


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])
    remember = BooleanField('Remember me')


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=4, max=15)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=8, max=80)])

    def validate_username(self, username):
        user_ref = db.collection('users').document(username.data).get()
        if user_ref.exists:
            raise ValidationError('That username is taken. Please choose a different one.')


class UploadForm(FlaskForm):
    title = StringField('Article Title', validators=[InputRequired()])
    file = FileField('Upload Article', validators=[InputRequired()])
    submit = SubmitField('Upload')


def save_article_upload(form, submission_deadline=None, voting_deadline=None):
    """Shared upload logic used by both /dashboard and /upload so behavior
    (extension check, safe filenames, unique names) is consistent everywhere."""
    file = form.file.data
    filename = secure_filename(file.filename)

    if not filename.lower().endswith('.pdf'):
        flash('Only PDF files are allowed.')
        return False

    unique_filename = f"{uuid.uuid4().hex}_{filename}"

    upload_folder = app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    local_path = os.path.join(upload_folder, unique_filename)
    file.save(local_path)

    storage_path = f'journal_club/pdfs/{unique_filename}'
    upload_result = cloudinary.uploader.upload(
        local_path,
        resource_type='raw',  # PDFs aren't images, so store as a raw asset
        public_id=storage_path,
        overwrite=False,
    )
    file_url = upload_result['secure_url']
    cloudinary_public_id = upload_result['public_id']

    now = datetime.now()
    if not submission_deadline:
        submission_deadline = now + timedelta(days=7)
    if not voting_deadline:
        voting_deadline = now + timedelta(days=14)

    # Articles are tagged with the month of the meeting they'll be discussed
    # at (the NEXT calendar month), not the month they were uploaded in.
    if now.month == 12:
        target_month = datetime(now.year + 1, 1, 1)
    else:
        target_month = datetime(now.year, now.month + 1, 1)

    article_data = {
        'title': form.title.data,
        'file_url': file_url,
        'cloudinary_public_id': cloudinary_public_id,
        'votes': 0,
        'emoji_votes': {},
        'user_id': current_user.id,
        'user_name': current_user.username,
        'emoji': current_user.emoji,
        'created_at': now,
        'voting_month': target_month.strftime('%Y-%m'),
        'submission_deadline': submission_deadline,
        'voting_deadline': voting_deadline,
        'voted_users': []
    }
    db.collection('articles').add(article_data)
    flash('Article uploaded successfully!')
    return True


@app.route('/')
def index():
    articles = db.collection('articles').where('voting_month', '==', datetime.now().strftime('%Y-%m')).stream()
    articles_list = [{'id': a.id, **a.to_dict()} for a in articles]
    return render_template('index.html', articles=articles_list)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user_ref = db.collection('users').document(form.username.data).get()
        if user_ref.exists:
            user_data = user_ref.to_dict()
            user = User(
                user_id=form.username.data,
                username=user_data['username'],
                password=user_data['password'],
                emoji=user_data['emoji'],
                is_admin=_resolve_is_admin(form.username.data, user_data),
            )
            if check_password_hash(user.password, form.password.data):
                login_user(user, remember=form.remember.data)
                return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html', form=form)


@app.route('/user')
@login_required
def user():
    articles = db.collection('articles') \
        .where('user_id', '==', current_user.id) \
        .stream()

    articles_list = [{'id': a.id, **a.to_dict()} for a in articles]

    user_doc = db.collection('users').document(current_user.id).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}

    # Ensure joker fields always exist so templates don't have to guess/crash
    # on a comparison against an undefined value.
    user_data.setdefault('joker_remaining', MAX_JOKERS_PER_YEAR)
    user_data.setdefault('joker_used_month', None)

    return render_template(
        "user.html",
        articles=articles_list,
        user_data=user_data,
        current_month=datetime.now().strftime("%Y-%m")
    )


@app.route('/use_joker', methods=['POST'])
@login_required
def use_joker():
    current_month = datetime.now().strftime('%Y-%m')
    user_ref = db.collection('users').document(current_user.id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        flash('User not found.')
        return redirect(url_for('user'))

    user_data = user_doc.to_dict()
    joker_remaining = user_data.get('joker_remaining', MAX_JOKERS_PER_YEAR)
    joker_used_month = user_data.get('joker_used_month')

    if joker_used_month == current_month:
        flash('You already used your joker this month.')
    elif joker_remaining <= 0:
        flash('You have no jokers remaining.')
    else:
        user_ref.update({
            'joker_remaining': joker_remaining - 1,
            'joker_used_month': current_month
        })
        flash('Joker used for this month! 🎭')

    return redirect(url_for('user'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        assigned_emoji = random.choice(EMOJI_LIST)
        user_data = {
            'username': form.username.data,
            'password': hashed_password,
            'emoji': assigned_emoji,
            'joker_remaining': MAX_JOKERS_PER_YEAR,
            'joker_used_month': None,
            'is_admin': False,
        }
        user_ref = db.collection('users').document(form.username.data)
        if user_ref.get().exists:
            flash('Username already taken. Please choose a different one.')
        else:
            user_ref.set(user_data)
            flash('Registration successful! You can now log in.')
            return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/delete_article/<article_id>', methods=['POST'])
@login_required
def delete_article(article_id):
    # Get the next parameter from the request to determine where to redirect
    next_page = request.args.get('next', 'dashboard')  # Default to 'dashboard' if not specified

    article_ref = db.collection('articles').document(article_id)
    article = article_ref.get()

    if article.exists:
        article_data = article.to_dict()
        if article_data['user_id'] == current_user.id:
            public_id = article_data.get('cloudinary_public_id')
            if public_id:
                try:
                    cloudinary.uploader.destroy(public_id, resource_type='raw')
                except Exception as e:
                    flash(f"Error deleting file from storage: {str(e)}")
            elif article_data.get('file_url'):
                # Article predates the Cloudinary migration (was on Firebase
                # Storage) — nothing to clean up here automatically.
                flash('Article deleted. Its old file was stored on Firebase and may need manual cleanup there.')
            else:
                flash('No file associated with this article.')

            # Delete article data from Firestore
            article_ref.delete()
            flash('Article deleted successfully!')
        else:
            flash('You are not authorized to delete this article.')
    else:
        flash('Article not found.')

    # Redirect based on the 'next' parameter
    if next_page == 'user':
        return redirect(url_for('user'))
    else:
        return redirect(url_for('dashboard'))


@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = UploadForm()
    today = datetime.now()
    current_month_key = today.strftime('%Y-%m')

    # The bucket that's currently open for new submissions is next calendar
    # month's meeting (see save_article_upload).
    if today.month == 12:
        next_month = datetime(today.year + 1, 1, 1)
    else:
        next_month = datetime(today.year, today.month + 1, 1)
    next_month_key = next_month.strftime('%Y-%m')

    # Upload logic (shared with /upload — validates extension, uses safe/unique filenames)
    if form.validate_on_submit():
        try:
            if save_article_upload(form):
                return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"An error occurred during upload: {str(e)}")
            print(f"Upload error: {str(e)}")

    # Load ALL articles and group them by the month they'll be discussed in.
    try:
        articles = db.collection('articles').stream()
        all_articles = []
        for a in articles:
            article = {'id': a.id, **a.to_dict()}
            article.setdefault('emoji_votes', {})
            article.setdefault('votes', 0)
            all_articles.append(article)
    except Exception as e:
        print(f"Error fetching articles: {e}")
        flash("Error loading articles.")
        all_articles = []

    groups = {}
    for article in all_articles:
        key = article.get('voting_month', 'unknown')
        groups.setdefault(key, []).append(article)

    # Always show the currently-open submission bucket, even if it's empty.
    groups.setdefault(next_month_key, [])

    # Fallback deadline info (from the next scheduled meeting) for buckets
    # that don't have any articles yet to pull a deadline from.
    fallback_submission_deadline, fallback_voting_deadline = get_upcoming_meeting_dates()

    journal_clubs = []
    for key in sorted(groups.keys(), reverse=True):
        arts = sorted(groups[key], key=lambda a: a.get('votes', 0), reverse=True)

        try:
            display_name = datetime.strptime(key, '%Y-%m').strftime('%B %Y')
        except ValueError:
            display_name = key

        is_past = key < current_month_key
        winner = None
        deadline = None

        if is_past:
            if arts:
                winner = max(arts, key=lambda a: a.get('votes', 0))
        else:
            deadlines = [a.get('voting_deadline') for a in arts if a.get('voting_deadline')]
            if deadlines:
                deadline = max(deadlines)
            elif fallback_voting_deadline:
                deadline = fallback_voting_deadline

        journal_clubs.append({
            'key': key,
            'display_name': display_name,
            'articles': arts,
            'winner': winner,
            'deadline': deadline,
            'is_current': key == current_month_key,
        })

    return render_template(
        'dashboard.html',
        form=form,
        journal_clubs=journal_clubs,
        now=today
    )


@app.route('/article/<article_id>')
@login_required
def view_article(article_id):
    article_ref = db.collection('articles').document(article_id).get()
    if article_ref.exists:
        article_data = article_ref.to_dict()
        pdf_url = article_data.get('file_url', None)
        return render_template('view_article.html', article=article_data, pdf_url=pdf_url)
    else:
        flash('Article not found.')
        return redirect(url_for('dashboard'))


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = UploadForm()

    if form.validate_on_submit():
        submission_deadline, voting_deadline = get_upcoming_meeting_dates()
        try:
            save_article_upload(form, submission_deadline, voting_deadline)
        except Exception as e:
            flash(f"An error occurred during upload: {str(e)}")
            print(f"Upload error: {str(e)}")
        return redirect(url_for('dashboard'))

    # Fetch uploaded articles by current user
    user_articles = db.collection('articles').where('user_id', '==', current_user.id).stream()
    articles_list = [{'id': a.id, **a.to_dict()} for a in user_articles]

    return render_template('upload_article.html', form=form, articles=articles_list)


def get_upcoming_meeting_dates():
    try:
        meetings_ref = db.collection('meetings')
        upcoming_meeting = meetings_ref.order_by('meeting_date').where('meeting_date', '>=', datetime.now()).limit(1).stream()
        upcoming_meeting_data = list(upcoming_meeting)

        if upcoming_meeting_data:
            meeting = upcoming_meeting_data[0]
            submission_deadline = meeting.to_dict().get('submission_deadline')
            voting_deadline = meeting.to_dict().get('voting_deadline')
            return submission_deadline, voting_deadline
        else:
            print("No upcoming meetings found.")
            return None, None
    except Exception as e:
        print(f"Error fetching upcoming meeting dates: {str(e)}")
        return None, None


@app.route('/meetings')
@login_required
def meetings():
    meetings_ref = db.collection('meetings').stream()
    meetings_list = [{'id': meeting.id, **meeting.to_dict()} for meeting in meetings_ref]
    return render_template('meetings.html', meetings=meetings_list)


@app.route('/unvote/<article_id>', methods=['POST'])
@login_required
def unvote(article_id):
    try:
        article_ref = db.collection('articles').document(article_id)
        article = article_ref.get()
        if not article.exists:
            flash("Article not found.")
            return redirect(url_for('dashboard'))

        data = article.to_dict()

        emoji_votes = data.get('emoji_votes', {})
        voted_users = data.get('voted_users', [])

        if current_user.id in emoji_votes:
            del emoji_votes[current_user.id]
        if current_user.id in voted_users:
            voted_users.remove(current_user.id)

        article_ref.update({
            'emoji_votes': emoji_votes,
            'voted_users': voted_users,
            'votes': len(emoji_votes)
        })

        flash("Your vote has been withdrawn.")
    except Exception as e:
        print(f"Error withdrawing vote: {e}")
        flash("An error occurred while withdrawing your vote.")

    return redirect(url_for('dashboard'))


@app.route('/emoji_vote/<article_id>/<emoji>', methods=['POST'])
@login_required
def emoji_vote(article_id, emoji):
    try:
        article_ref = db.collection('articles').document(article_id)
        article = article_ref.get()

        if not article.exists:
            flash('Article not found.')
            return redirect(url_for('dashboard'))

        article_data = article.to_dict()

        emoji_votes = article_data.get('emoji_votes', {})
        voted_users = article_data.get('voted_users', [])

        if current_user.id in voted_users:
            flash('You have already voted for this article.')
            return redirect(url_for('dashboard'))

        emoji_votes[current_user.id] = emoji
        voted_users.append(current_user.id)

        article_ref.update({
            'emoji_votes': emoji_votes,
            'voted_users': voted_users,
            'votes': len(emoji_votes)
        })

        flash('Vote submitted successfully!')

    except Exception as e:
        print(f"Voting error: {e}")
        flash('An error occurred while voting.')

    return redirect(url_for('dashboard'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/add_meeting', methods=['GET', 'POST'])
@login_required
def add_meeting():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            # NOTE: field name is `meeting_date`, matching what
            # get_upcoming_meeting_dates() queries on. It used to be saved
            # as `date`, which meant deadlines were never actually found.
            meeting_date = datetime.strptime(request.form['date'], '%Y-%m-%d')
        except (KeyError, ValueError):
            flash('Please provide a valid meeting date.')
            return redirect(url_for('add_meeting'))

        meeting_data = {
            'title': request.form.get('title', ''),
            'description': request.form.get('description', ''),
            'meeting_date': meeting_date,
            'submission_deadline': meeting_date - timedelta(days=7),
            'voting_deadline': meeting_date - timedelta(days=1),
        }
        db.collection('meetings').document().set(meeting_data)
        flash('Meeting added successfully!')
        return redirect(url_for('meetings'))

    return render_template('add_meeting.html')


@app.route('/admin/toggle_admin/<user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    if user_id == current_user.id:
        flash("You can't change your own admin status.")
        return redirect(url_for('settings'))

    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        flash('User not found.')
        return redirect(url_for('settings'))

    currently_admin = _resolve_is_admin(user_id, user_doc.to_dict())
    user_ref.update({'is_admin': not currently_admin})
    flash(f"Admin access {'removed from' if currently_admin else 'granted to'} {user_id}.")
    return redirect(url_for('settings'))


@app.route('/admin/delete_user/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    if user_id == current_user.id:
        flash("You can't delete your own account.")
        return redirect(url_for('settings'))

    db.collection('users').document(user_id).delete()
    flash(f"User '{user_id}' deleted. Articles they submitted are kept as-is.")
    return redirect(url_for('settings'))


@app.route('/admin/meetings/<meeting_id>/cancel', methods=['POST'])
@login_required
def cancel_meeting(meeting_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    db.collection('meetings').document(meeting_id).delete()
    flash('Meeting cancelled.')
    return redirect(url_for('settings'))


@app.route('/admin/meetings/<meeting_id>/reschedule', methods=['POST'])
@login_required
def reschedule_meeting(meeting_id):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    new_date_str = request.form.get('meeting_date')
    if not new_date_str:
        flash('Please provide a new meeting date.')
        return redirect(url_for('settings'))

    try:
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d')
    except ValueError:
        flash('Invalid date format.')
        return redirect(url_for('settings'))

    db.collection('meetings').document(meeting_id).update({
        'meeting_date': new_date,
        'submission_deadline': new_date - timedelta(days=7),
        'voting_deadline': new_date - timedelta(days=1),
    })
    flash('Meeting rescheduled.')
    return redirect(url_for('settings'))


@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    users = db.collection('users').stream()
    articles = db.collection('articles').stream()
    meetings = db.collection('meetings').stream()

    return render_template('admin_panel.html', users=[u.to_dict() for u in users],
                           articles=[{'id': a.id, **a.to_dict()} for a in articles],
                           meetings=[m.to_dict() for m in meetings])


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm()
    if request.method == 'GET':
        form.emoji.data = current_user.emoji

    if form.validate_on_submit():
        db.collection('users').document(current_user.id).update({'emoji': form.emoji.data})
        flash('Emoji updated!')
        return redirect(url_for('settings'))

    admin_data = None
    if current_user.is_admin:
        users_list = []
        for u in db.collection('users').stream():
            d = u.to_dict()
            users_list.append({
                'id': u.id,
                'username': d.get('username', u.id),
                'emoji': d.get('emoji', ''),
                'is_admin': _resolve_is_admin(u.id, d),
            })
        users_list.sort(key=lambda x: (not x['is_admin'], x['username'].lower()))

        meetings_list = [{'id': m.id, **m.to_dict()} for m in db.collection('meetings').stream()]
        meetings_list.sort(key=lambda m: m.get('meeting_date') or datetime.max)

        admin_data = {'users': users_list, 'meetings': meetings_list}

    return render_template('settings.html', form=form, admin_data=admin_data)


if __name__ == '__main__':
    # Set FLASK_DEBUG=1 in your environment for local dev instead of hardcoding debug=True.
    app.run(debug=os.getenv('FLASK_DEBUG', '0') == '1')