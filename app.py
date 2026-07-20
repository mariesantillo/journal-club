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


def _next_month(dt):
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1)
    return datetime(dt.year, dt.month + 1, 1)


def _month_display_name(key):
    try:
        return datetime.strptime(key, '%Y-%m').strftime('%B %Y')
    except ValueError:
        return key


def _pick_winner(articles):
    """Highest votes wins; ties are broken by whichever article was
    submitted earliest (first-come-first-served, deterministic)."""
    if not articles:
        return None
    return min(articles, key=lambda a: (-a.get('votes', 0), a.get('created_at') or datetime.max))


def _close_cycle(month_key, cycle=None):
    """Compute the winner for a month and mark its cycle as closed/announced."""
    articles = [{'id': a.id, **a.to_dict()} for a in db.collection('articles').where('voting_month', '==', month_key).stream()]
    winner = _pick_winner(articles)
    db.collection('meetings').document(month_key).set({
        'voting_open': False,
        'winner_announced': True,
        'winner_article_id': winner['id'] if winner else None,
        'announced_at': datetime.now(),
    }, merge=True)
    return winner


def _auto_close_expired_cycles():
    """Lazily close out any voting cycle whose deadline has passed. There's
    no real cron job here — this runs whenever someone loads the dashboard,
    so the first visitor after a deadline triggers the winner computation."""
    now = datetime.now()
    current_key = now.strftime('%Y-%m')

    for c in db.collection('meetings').where('voting_open', '==', True).stream():
        cycle = c.to_dict()
        deadline = cycle.get('voting_deadline')
        if deadline and deadline < now:
            _close_cycle(c.id, cycle)

    # Also close the real current month once its deadline passes, even if no
    # admin ever explicitly opened it (calendar-default behavior).
    current_doc = db.collection('meetings').document(current_key).get()
    if current_doc.exists:
        cycle = current_doc.to_dict()
        deadline = cycle.get('voting_deadline')
        if cycle.get('voting_open', True) and not cycle.get('winner_announced') and deadline and deadline < now:
            _close_cycle(current_key, cycle)


def save_article_upload(form):
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

    # Articles are tagged with the month of the meeting they'll be discussed
    # at (the NEXT calendar month), not the month they were uploaded in.
    target_key = _next_month(now).strftime('%Y-%m')

    # Pull deadlines from whatever the admin has set for that month's cycle,
    # falling back to generic +7/+14 day defaults if nothing's been set.
    cycle_doc = db.collection('meetings').document(target_key).get()
    cycle = cycle_doc.to_dict() if cycle_doc.exists else {}
    submission_deadline = cycle.get('submission_deadline') or (now + timedelta(days=7))
    voting_deadline = cycle.get('voting_deadline') or (now + timedelta(days=14))

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
        'voting_month': target_key,
        'submission_deadline': submission_deadline,
        'voting_deadline': voting_deadline,
        'voted_users': []
    }
    db.collection('articles').add(article_data)
    flash('Article uploaded successfully!')
    return True


def _get_pending_announcement():
    """Most recently closed voting cycle that this browser hasn't dismissed
    yet, with the winning article's details attached. Shared by / and
    /dashboard so both show the same announcement + confetti."""
    dismissed = session.get('dismissed_announcements', [])
    cycles = {c.id: c.to_dict() for c in db.collection('meetings').stream()}
    announced = sorted(
        [(k, c) for k, c in cycles.items() if c.get('winner_announced') and k not in dismissed],
        key=lambda kv: kv[1].get('announced_at') or datetime.min,
        reverse=True,
    )
    if not announced:
        return None

    ann_key, ann_cycle = announced[0]
    winner_id = ann_cycle.get('winner_article_id')
    if not winner_id:
        return None

    winner_doc = db.collection('articles').document(winner_id).get()
    if not winner_doc.exists:
        return None

    w = winner_doc.to_dict()
    return {
        'month_key': ann_key,
        'display_name': _month_display_name(ann_key),
        'title': w.get('title'),
        'user_name': w.get('user_name'),
    }


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    _auto_close_expired_cycles()
    return render_template('index.html', announcement=_get_pending_announcement())


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

    # Attach "won X Journal Club" info to any article that was a past winner.
    winner_map = {}
    for c in db.collection('meetings').where('winner_announced', '==', True).stream():
        d = c.to_dict()
        winner_id = d.get('winner_article_id')
        if winner_id:
            winner_map[winner_id] = _month_display_name(c.id)
    for article in articles_list:
        article['won_month'] = winner_map.get(article['id'])

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
    next_month_key = _next_month(today).strftime('%Y-%m')

    # Upload logic (shared with /upload — validates extension, uses safe/unique filenames)
    if form.validate_on_submit():
        try:
            if save_article_upload(form):
                return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"An error occurred during upload: {str(e)}")
            print(f"Upload error: {str(e)}")

    # Close out any voting cycle whose deadline has passed (see docstring).
    _auto_close_expired_cycles()

    # Look up everyone's CURRENT emoji so the dashboard reflects emoji
    # changes made in Settings, even on articles submitted long ago.
    try:
        user_emoji_map = {u.id: u.to_dict().get('emoji', '') for u in db.collection('users').stream()}
    except Exception as e:
        print(f"Error fetching users for emoji lookup: {e}")
        user_emoji_map = {}

    try:
        all_articles = []
        for a in db.collection('articles').stream():
            article = {'id': a.id, **a.to_dict()}
            article.setdefault('emoji_votes', {})
            article.setdefault('votes', 0)
            article['emoji'] = user_emoji_map.get(article.get('user_id'), article.get('emoji', ''))
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

    cycles = {c.id: c.to_dict() for c in db.collection('meetings').stream()}

    journal_clubs = []
    for key in sorted(groups.keys(), reverse=True):
        arts = sorted(groups[key], key=lambda a: a.get('votes', 0), reverse=True)
        cycle = cycles.get(key, {})

        # If an admin has explicitly managed this month's cycle, use that.
        # Otherwise fall back to plain calendar-based defaults.
        is_open = cycle.get('voting_open', key == current_month_key)
        is_closed = cycle.get('winner_announced', key < current_month_key)

        winner = None
        deadline = None

        if is_closed:
            winner_id = cycle.get('winner_article_id')
            if winner_id:
                winner = next((a for a in arts if a['id'] == winner_id), None)
            if not winner and arts:
                winner = _pick_winner(arts)
        else:
            deadline = cycle.get('voting_deadline')
            if not deadline and arts:
                deadlines = [a.get('voting_deadline') for a in arts if a.get('voting_deadline')]
                if deadlines:
                    deadline = max(deadlines)

        journal_clubs.append({
            'key': key,
            'display_name': _month_display_name(key),
            'articles': arts,
            'winner': winner,
            'deadline': deadline,
            'is_open': is_open,
        })

    # Winner-announcement popup: shows the most recently closed cycle, and
    # persists (for this browser) until dismissed — not just for the first
    # visitor after the deadline.
    announcement = _get_pending_announcement()

    return render_template(
        'dashboard.html',
        form=form,
        journal_clubs=journal_clubs,
        announcement=announcement,
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
        try:
            save_article_upload(form)
        except Exception as e:
            flash(f"An error occurred during upload: {str(e)}")
            print(f"Upload error: {str(e)}")
        return redirect(url_for('dashboard'))

    # Fetch uploaded articles by current user
    user_articles = db.collection('articles').where('user_id', '==', current_user.id).stream()
    articles_list = [{'id': a.id, **a.to_dict()} for a in user_articles]

    return render_template('upload_article.html', form=form, articles=articles_list)


@app.route('/dismiss_announcement/<month_key>', methods=['POST'])
def dismiss_announcement(month_key):
    dismissed = session.get('dismissed_announcements', [])
    if month_key not in dismissed:
        dismissed.append(month_key)
    session['dismissed_announcements'] = dismissed
    return redirect(request.referrer or url_for('dashboard'))


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


@app.route('/admin/cycles/save', methods=['POST'])
@login_required
def save_cycle():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    month_key = request.form.get('month')  # from <input type="month">, e.g. "2026-08"
    submission_str = request.form.get('submission_deadline')
    voting_str = request.form.get('voting_deadline')
    meeting_str = request.form.get('meeting_date')

    if not month_key:
        flash('Please choose a month.')
        return redirect(url_for('settings'))

    update = {}
    try:
        if submission_str:
            update['submission_deadline'] = datetime.strptime(submission_str, '%Y-%m-%d')
        if voting_str:
            update['voting_deadline'] = datetime.strptime(voting_str, '%Y-%m-%d')
        if meeting_str:
            update['meeting_date'] = datetime.strptime(meeting_str, '%Y-%m-%d')
    except ValueError:
        flash('Invalid date format.')
        return redirect(url_for('settings'))

    if not update:
        flash('Please provide at least one date.')
        return redirect(url_for('settings'))

    db.collection('meetings').document(month_key).set(update, merge=True)
    flash(f'Dates saved for {_month_display_name(month_key)}.')
    return redirect(url_for('settings'))


@app.route('/admin/cycles/<month_key>/delete', methods=['POST'])
@login_required
def delete_cycle(month_key):
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    db.collection('meetings').document(month_key).delete()
    flash(f'Deadline info for {_month_display_name(month_key)} deleted. Its articles keep their own deadlines.')
    return redirect(url_for('settings'))


@app.route('/admin/cycles/open_next', methods=['POST'])
@login_required
def open_next_cycle():
    if not current_user.is_admin:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    now = datetime.now()
    current_key = now.strftime('%Y-%m')
    next_key = _next_month(now).strftime('%Y-%m')

    explicitly_open = list(db.collection('meetings').where('voting_open', '==', True).stream())
    if explicitly_open:
        for c in explicitly_open:
            _close_cycle(c.id, c.to_dict())
    else:
        # Nothing was explicitly opened yet, so the real current month was
        # open by calendar default — close that one out now.
        current_doc = db.collection('meetings').document(current_key).get()
        _close_cycle(current_key, current_doc.to_dict() if current_doc.exists else {})

    db.collection('meetings').document(next_key).set({
        'voting_open': True,
        'winner_announced': False,
        'winner_article_id': None,
    }, merge=True)

    flash(f'Voting is now open for {_month_display_name(next_key)}.')
    return redirect(url_for('settings'))


@app.route('/meetings')
@login_required
def meetings():
    cycles_list = []
    for c in db.collection('meetings').stream():
        d = c.to_dict()
        cycles_list.append({
            'key': c.id,
            'display_name': _month_display_name(c.id),
            'submission_deadline': d.get('submission_deadline'),
            'voting_deadline': d.get('voting_deadline'),
            'meeting_date': d.get('meeting_date'),
            'voting_open': d.get('voting_open', False),
            'winner_announced': d.get('winner_announced', False),
        })
    cycles_list.sort(key=lambda c: c['key'], reverse=True)
    return render_template('meetings.html', cycles=cycles_list)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm()
    if request.method == 'GET':
        form.emoji.data = current_user.emoji

    taken_emojis = {
        d.get('emoji')
        for u in db.collection('users').stream()
        for d in [u.to_dict()]
        if u.id != current_user.id and d.get('emoji')
    }

    if form.validate_on_submit():
        chosen = form.emoji.data
        if chosen != current_user.emoji and chosen in taken_emojis:
            flash('That emoji is already taken by another member — pick a different one.')
        else:
            db.collection('users').document(current_user.id).update({'emoji': chosen})
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

        cycles_list = []
        for c in db.collection('meetings').stream():
            d = c.to_dict()
            cycles_list.append({
                'key': c.id,
                'display_name': _month_display_name(c.id),
                'submission_deadline': d.get('submission_deadline'),
                'voting_deadline': d.get('voting_deadline'),
                'meeting_date': d.get('meeting_date'),
                'voting_open': d.get('voting_open', False),
                'winner_announced': d.get('winner_announced', False),
            })
        cycles_list.sort(key=lambda c: c['key'], reverse=True)

        admin_data = {'users': users_list, 'cycles': cycles_list}

    return render_template('settings.html', form=form, admin_data=admin_data, taken_emojis=taken_emojis)


if __name__ == '__main__':
    # Set FLASK_DEBUG=1 in your environment for local dev instead of hardcoding debug=True.
    app.run(debug=os.getenv('FLASK_DEBUG', '0') == '1')