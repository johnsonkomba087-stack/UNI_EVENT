from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import pathlib
import io
import secrets
import smtplib
import hmac
import hashlib
from email.message import EmailMessage
import qrcode

# App setup
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
app = Flask(__name__, 
            template_folder=str(BASE_DIR / 'templates'),
            static_folder=str(BASE_DIR / 'frontend'))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR / "events.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = str(BASE_DIR / 'frontend' / 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# ==================== MODELS ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='student')  # student, organizer, admin
    department = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    events_created = db.relationship('Event', backref='organizer', lazy=True)
    registrations = db.relationship('Registration', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Academic, Cultural, Sports, Workshop, Seminar, Social
    location = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, default=50)
    image_url = db.Column(db.String(300), default='')
    status = db.Column(db.String(20), default='upcoming')  # upcoming, ongoing, completed, cancelled
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    registrations = db.relationship('Registration', backref='event', lazy=True, cascade='all, delete-orphan')

    @property
    def registered_count(self):
        return len([r for r in self.registrations if r.status == 'registered'])

    @property
    def spots_left(self):
        return max(0, self.capacity - self.registered_count)

    @property
    def is_full(self):
        return self.registered_count >= self.capacity


class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    status = db.Column(db.String(20), default='registered')  # registered, cancelled, attended
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'event_id', name='unique_registration'),)


# ==================== HELPERS ====================

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


def send_notification(to_email, subject, body):
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    from_email = os.getenv('SMTP_FROM', smtp_user or 'no-reply@university-events.local')

    if not smtp_host:
        app.logger.info("Email notification (SMTP not configured): %s <%s>", subject, to_email)
        return

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = from_email
    message['To'] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if os.getenv('SMTP_USE_TLS', '1') == '1':
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_password or '')
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        app.logger.error("Could not send email notification to %s: %s", to_email, exc)


def save_event_image():
    file = request.files.get('image_file')
    if not file or not file.filename:
        return request.form.get('image_url', '').strip()

    filename = secure_filename(file.filename)
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if extension not in app.config['ALLOWED_IMAGE_EXTENSIONS']:
        raise ValueError('Please upload a PNG, JPG, JPEG, GIF, or WEBP image.')

    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
    return url_for('uploaded_file', filename=unique_name)


def make_checkin_token(registration):
    payload = f"{registration.id}:{registration.user_id}:{registration.event_id}"
    signature = hmac.new(app.config['SECRET_KEY'].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_checkin_token(token):
    try:
        parts = token.rsplit(':', 1)
        if len(parts) != 2:
            return None
        payload, signature = parts
        expected = hmac.new(app.config['SECRET_KEY'].encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        registration_id, user_id, event_id = (int(value) for value in payload.split(':'))
        return Registration.query.filter_by(
            id=registration_id,
            user_id=user_id,
            event_id=event_id,
            status='registered'
        ).first()
    except (ValueError, AttributeError):
        return None


# ==================== ROUTES ====================

@app.route('/')
def home():
    now = datetime.utcnow()
    # Auto-update event statuses
    events = Event.query.all()
    for e in events:
        if e.status != 'cancelled':
            if e.end_time < now:
                e.status = 'completed'
            elif e.start_time <= now <= e.end_time:
                e.status = 'ongoing'
            else:
                e.status = 'upcoming'
    db.session.commit()

    upcoming = Event.query.filter(
        Event.status.in_(['upcoming', 'ongoing']),
        Event.start_time >= now - timedelta(hours=2)
    ).order_by(Event.start_time).limit(6).all()

    categories = db.session.query(Event.category, db.func.count(Event.id)).group_by(Event.category).all()
    total_events = Event.query.count()
    total_users = User.query.count()
    total_regs = Registration.query.filter_by(status='registered').count()

    return render_template('index.html', 
                           events=upcoming, 
                           categories=categories,
                           total_events=total_events,
                           total_users=total_users,
                           total_regs=total_regs,
                           user=get_current_user())


@app.route('/events')
def events():
    category = request.args.get('category', '')
    search = request.args.get('search', '')
    status = request.args.get('status', 'upcoming')

    query = Event.query

    if category:
        query = query.filter(Event.category == category)
    if search:
        query = query.filter(
            db.or_(
                Event.title.ilike(f'%{search}%'),
                Event.description.ilike(f'%{search}%'),
                Event.location.ilike(f'%{search}%')
            )
        )
    if status and status != 'all':
        query = query.filter(Event.status == status)

    events_list = query.order_by(Event.start_time).all()
    categories = ['Academic', 'Cultural', 'Sports', 'Workshop', 'Seminar', 'Social']

    return render_template('events.html', 
                           events=events_list, 
                           categories=categories,
                           selected_category=category,
                           search=search,
                           selected_status=status,
                           user=get_current_user())


@app.route('/event/<int:event_id>')
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    user = get_current_user()
    is_registered = False
    is_waitlisted = False
    if user:
        reg = Registration.query.filter_by(user_id=user.id, event_id=event.id, status='registered').first()
        is_registered = reg is not None
        if not is_registered:
            is_waitlisted = Registration.query.filter_by(
                user_id=user.id, event_id=event.id, status='waitlisted'
            ).first() is not None

    return render_template('event_detail.html', 
                           event=event, 
                           is_registered=is_registered,
                           is_waitlisted=is_waitlisted,
                           user=user)


@app.route('/register/<int:event_id>', methods=['POST'])
@login_required
def register_event(event_id):
    event = Event.query.get_or_404(event_id)
    user = get_current_user()

    if event.status in ['completed', 'cancelled']:
        flash('Cannot register for this event.', 'danger')
        return redirect(url_for('event_detail', event_id=event_id))

    existing = Registration.query.filter_by(user_id=user.id, event_id=event.id).first()
    if existing:
        if existing.status == 'registered':
            flash('You are already registered.', 'info')
        elif existing.status == 'waitlisted':
            flash('You are already on the waitlist.', 'info')
        else:
            existing.status = 'waitlisted' if event.is_full else 'registered'
            existing.registered_at = datetime.utcnow()
            db.session.commit()
            if existing.status == 'waitlisted':
                flash('This event is full. You have been added to the waitlist.', 'warning')
            else:
                flash('Successfully re-registered for the event!', 'success')
    else:
        reg = Registration(
            user_id=user.id,
            event_id=event.id,
            status='waitlisted' if event.is_full else 'registered'
        )
        db.session.add(reg)
        db.session.commit()
        if reg.status == 'waitlisted':
            flash('This event is full. You have been added to the waitlist.', 'warning')
        else:
            send_notification(
                user.email,
                f'Registration confirmed: {event.title}',
                f'Your registration for "{event.title}" is confirmed.\n'
                f'Date: {event.start_time.strftime("%A, %b %d, %Y at %H:%M")}\n'
                f'Location: {event.location}'
            )
            flash('Successfully registered for the event!', 'success')

    return redirect(url_for('event_detail', event_id=event_id))


@app.route('/unregister/<int:event_id>', methods=['POST'])
@login_required
def unregister_event(event_id):
    user = get_current_user()
    reg = Registration.query.filter_by(user_id=user.id, event_id=event_id, status='registered').first()
    if reg:
        reg.status = 'cancelled'
        event = Event.query.get(event_id)
        if event and not event.is_full:
            waitlisted = Registration.query.filter_by(
                event_id=event.id, status='waitlisted'
            ).order_by(Registration.registered_at.asc()).first()
            if waitlisted:
                waitlisted.status = 'registered'
                waitlisted.registered_at = datetime.utcnow()
                promoted_user = User.query.get(waitlisted.user_id)
                send_notification(
                    promoted_user.email,
                    f'You have a spot: {event.title}',
                    f'A spot opened up and you have been promoted from the waitlist.\n'
                    f'Date: {event.start_time.strftime("%A, %b %d, %Y at %H:%M")}\n'
                    f'Location: {event.location}'
                )
        db.session.commit()
        flash('You have unregistered from the event.', 'info')
    return redirect(url_for('event_detail', event_id=event_id))


@app.route('/leave-waitlist/<int:event_id>', methods=['POST'])
@login_required
def leave_waitlist(event_id):
    user = get_current_user()
    reg = Registration.query.filter_by(
        user_id=user.id, event_id=event_id, status='waitlisted'
    ).first()
    if reg:
        reg.status = 'cancelled'
        db.session.commit()
        flash('You have left the waitlist.', 'info')
    return redirect(url_for('event_detail', event_id=event_id))


@app.route('/my-events')
@login_required
def my_events():
    user = get_current_user()
    regs = Registration.query.filter_by(user_id=user.id, status='registered').all()
    waitlisted = Registration.query.filter_by(user_id=user.id, status='waitlisted').all()
    created = Event.query.filter_by(created_by=user.id).order_by(Event.start_time.desc()).all()
    return render_template(
        'my_events.html',
        registrations=regs,
        waitlisted=waitlisted,
        created_events=created,
        user=user
    )


@app.route('/create-event', methods=['GET', 'POST'])
@login_required
def create_event():
    user = get_current_user()
    if user.role not in ['organizer', 'admin']:
        flash('Only organizers and admins can create events.', 'danger')
        return redirect(url_for('home'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category')
        location = request.form.get('location', '').strip()
        start_str = request.form.get('start_time')
        end_str = request.form.get('end_time')
        capacity = request.form.get('capacity', 50)
        try:
            image_url = save_event_image()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('create_event'))

        if not all([title, description, category, location, start_str, end_str]):
            flash('Please fill all required fields.', 'danger')
            return redirect(url_for('create_event'))

        try:
            start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
            end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')
            capacity = int(capacity)
        except ValueError:
            flash('Invalid date or capacity format.', 'danger')
            return redirect(url_for('create_event'))

        if end_time <= start_time:
            flash('End time must be after start time.', 'danger')
            return redirect(url_for('create_event'))

        event = Event(
            title=title,
            description=description,
            category=category,
            location=location,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
            image_url=image_url,
            created_by=user.id
        )
        db.session.add(event)
        db.session.commit()
        flash('Event created successfully!', 'success')
        return redirect(url_for('event_detail', event_id=event.id))

    categories = ['Academic', 'Cultural', 'Sports', 'Workshop', 'Seminar', 'Social']
    return render_template('create_event.html', categories=categories, user=user)


@app.route('/edit-event/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    user = get_current_user()

    if user.role != 'admin' and event.created_by != user.id:
        flash('You can only edit your own events.', 'danger')
        return redirect(url_for('event_detail', event_id=event_id))

    if request.method == 'POST':
        event.title = request.form.get('title', event.title).strip()
        event.description = request.form.get('description', event.description).strip()
        event.category = request.form.get('category', event.category)
        event.location = request.form.get('location', event.location).strip()
        try:
            event.image_url = save_event_image() or event.image_url
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('edit_event', event_id=event_id))
        event.capacity = int(request.form.get('capacity', event.capacity))
        event.status = request.form.get('status', event.status)

        start_str = request.form.get('start_time')
        end_str = request.form.get('end_time')
        if start_str:
            event.start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        if end_str:
            event.end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')

        db.session.commit()
        flash('Event updated successfully!', 'success')
        return redirect(url_for('event_detail', event_id=event.id))

    categories = ['Academic', 'Cultural', 'Sports', 'Workshop', 'Seminar', 'Social']
    return render_template('edit_event.html', event=event, categories=categories, user=user)


@app.route('/delete-event/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    user = get_current_user()

    if user.role != 'admin' and event.created_by != user.id:
        flash('You can only delete your own events.', 'danger')
        return redirect(url_for('event_detail', event_id=event_id))

    db.session.delete(event)
    db.session.commit()
    flash('Event deleted.', 'info')
    return redirect(url_for('events'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if get_current_user():
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(url_for('home'))
        flash('Invalid username or password.', 'danger')

    return render_template('login.html', user=None)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if get_current_user():
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        department = request.form.get('department', '').strip()
        role = request.form.get('role', 'student')

        if not all([username, email, full_name, password]):
            flash('Please fill all required fields.', 'danger')
            return redirect(url_for('register'))

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))

        # Only allow student or organizer on public register
        if role not in ['student', 'organizer']:
            role = 'student'

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            department=department,
            role=role
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', user=None)


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    events = Event.query.order_by(Event.created_at.desc()).all()
    regs = Registration.query.filter_by(status='registered').count()
    return render_template('admin.html', users=users, events=events, total_regs=regs, user=get_current_user())


@app.route('/admin/toggle-role/<int:user_id>', methods=['POST'])
@admin_required
def toggle_role(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('Cannot change your own role.', 'warning')
        return redirect(url_for('admin_dashboard'))

    roles = ['student', 'organizer', 'admin']
    idx = roles.index(user.role) if user.role in roles else 0
    user.role = roles[(idx + 1) % len(roles)]
    db.session.commit()
    flash(f'{user.username} is now {user.role}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('Cannot delete yourself.', 'warning')
        return redirect(url_for('admin_dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted.', 'info')
    return redirect(url_for('admin_dashboard'))


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))


@app.route('/calendar')
def calendar():
    return render_template('calendar.html', user=get_current_user())


@app.route('/event/<int:event_id>/qr')
@login_required
def event_qr(event_id):
    user = get_current_user()
    registration = Registration.query.filter_by(
        user_id=user.id, event_id=event_id, status='registered'
    ).first()
    if not registration:
        return redirect(url_for('event_detail', event_id=event_id))

    checkin_url = url_for(
        'checkin',
        token=make_checkin_token(registration),
        _external=True
    )
    image = qrcode.make(checkin_url)
    output = io.BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png', download_name='event-ticket.png')


@app.route('/checkin/<token>', methods=['GET', 'POST'])
@login_required
def checkin(token):
    user = get_current_user()
    registration = verify_checkin_token(token)
    if not registration:
        flash('Invalid or expired event ticket.', 'danger')
        return redirect(url_for('home'))

    event = Event.query.get(registration.event_id)
    if user.role not in ['organizer', 'admin'] and event.created_by != user.id:
        flash('Only organizers and admins can check in attendees.', 'danger')
        return redirect(url_for('event_detail', event_id=event.id))

    if request.method == 'POST' or registration.status == 'registered':
        registration.status = 'attended'
        db.session.commit()
        attendee = User.query.get(registration.user_id)
        flash(f'{attendee.full_name} checked in successfully.', 'success')
    return redirect(url_for('event_detail', event_id=event.id))


def event_to_dict(event):
    return {
        'id': event.id,
        'title': event.title,
        'description': event.description,
        'category': event.category,
        'location': event.location,
        'start_time': event.start_time.isoformat(),
        'end_time': event.end_time.isoformat(),
        'capacity': event.capacity,
        'registered': event.registered_count,
        'spots_left': event.spots_left,
        'status': event.status,
        'image_url': event.image_url
    }


@app.route('/api/events')
def api_events():
    events = Event.query.order_by(Event.start_time).all()
    return jsonify({'events': [event_to_dict(event) for event in events]})


@app.route('/api/events/<int:event_id>')
def api_event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify(event_to_dict(event))


@app.route('/api/calendar')
def api_calendar_events():
    events = Event.query.order_by(Event.start_time).all()
    return jsonify([{
        'id': event.id,
        'title': event.title,
        'start': event.start_time.isoformat(),
        'end': event.end_time.isoformat(),
        'url': url_for('event_detail', event_id=event.id),
        'backgroundColor': '#0d6efd'
    } for event in events])


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid username or password.'}), 401
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    return jsonify({'id': user.id, 'username': user.username, 'full_name': user.full_name, 'role': user.role})


@app.route('/api/my-events')
@login_required
def api_my_events():
    user = get_current_user()
    registrations = Registration.query.filter_by(user_id=user.id).all()
    return jsonify([{
        'event': event_to_dict(registration.event),
        'status': registration.status
    } for registration in registrations])


@app.route('/api/events/<int:event_id>/register', methods=['POST'])
@login_required
def api_register_event(event_id):
    event = Event.query.get_or_404(event_id)
    user = get_current_user()
    if event.status in ['completed', 'cancelled']:
        return jsonify({'error': 'Registration is closed.'}), 400

    existing = Registration.query.filter_by(user_id=user.id, event_id=event.id).first()
    if existing:
        if existing.status in ['registered', 'waitlisted']:
            return jsonify({'status': existing.status, 'event': event_to_dict(event)})
        existing.status = 'waitlisted' if event.is_full else 'registered'
        existing.registered_at = datetime.utcnow()
    else:
        existing = Registration(
            user_id=user.id,
            event_id=event.id,
            status='waitlisted' if event.is_full else 'registered'
        )
        db.session.add(existing)
    db.session.commit()
    return jsonify({'status': existing.status, 'event': event_to_dict(event)})


# ==================== INIT DB + SAMPLE DATA ====================

def init_db():
    with app.app_context():
        db.create_all()

        if User.query.count() == 0:
            seed_passwords = {
                'admin': os.getenv('SEED_ADMIN_PASSWORD'),
                'organizer': os.getenv('SEED_ORGANIZER_PASSWORD'),
                'student': os.getenv('SEED_STUDENT_PASSWORD')
            }
            if not all(seed_passwords.values()):
                raise RuntimeError(
                    'Set SEED_ADMIN_PASSWORD, SEED_ORGANIZER_PASSWORD, and '
                    'SEED_STUDENT_PASSWORD before initializing the sample accounts.'
                )

            # Admin
            admin = User(username='admin', email='admin@university.edu',
                         full_name='Demo Admin', role='admin', department='Computer Science')
            admin.set_password(seed_passwords['admin'])
            db.session.add(admin)

            # Organizer
            org = User(username='organizer1', email='org@university.edu',
                       full_name='SHEMA', role='organizer', department='Business')
            org.set_password(seed_passwords['organizer'])
            db.session.add(org)

            # Students
            s1 = User(username='student1', email='john@university.edu',
                      full_name='RONNIE', role='student', department='Engineering')
            s1.set_password(seed_passwords['student'])
            db.session.add(s1)

            s2 = User(username='student2', email='emma@university.edu',
                      full_name='Emma Wilson', role='student', department='AI')
            s2.set_password(seed_passwords['student'])
            db.session.add(s2)

            db.session.commit()

            # Sample events
            now = datetime.utcnow()
            events_data = [
                {
                    'title': 'AI & Robotics Workshop',
                    'description': 'Hands-on workshop covering inverse kinematics, servo control, and building simple robotic arms. Bring your laptop. Materials provided.',
                    'category': 'Workshop',
                    'location': 'Engineering Building - Lab 204',
                    'start_time': now + timedelta(days=3, hours=2),
                    'end_time': now + timedelta(days=3, hours=6),
                    'capacity': 30,
                    'created_by': org.id
                },
                {
                    'title': 'Annual Cultural Festival',
                    'description': 'Celebrate diversity with music, dance, food stalls, and performances from student clubs across campus.',
                    'category': 'Cultural',
                    'location': 'Main Campus Quad',
                    'start_time': now + timedelta(days=10),
                    'end_time': now + timedelta(days=10, hours=8),
                    'capacity': 500,
                    'created_by': admin.id
                },
                {
                    'title': 'Inter-Department Football Tournament',
                    'description': 'Friendly matches between departments. Register your team of 7 players. Prizes for winners!',
                    'category': 'Sports',
                    'location': 'University Sports Complex',
                    'start_time': now + timedelta(days=7),
                    'end_time': now + timedelta(days=9),
                    'capacity': 100,
                    'created_by': org.id
                },
                {
                    'title': 'Career Guidance Seminar',
                    'description': 'Industry experts share insights on job market trends, resume building, and interview skills for 2027 graduates.',
                    'category': 'Seminar',
                    'location': 'Lecture Hall A - Main Building',
                    'start_time': now + timedelta(days=5, hours=3),
                    'end_time': now + timedelta(days=5, hours=5),
                    'capacity': 150,
                    'created_by': admin.id
                },
                {
                    'title': 'Python for Data Science Bootcamp',
                    'description': '3-day intensive bootcamp covering pandas, numpy, matplotlib, and introductory machine learning.',
                    'category': 'Academic',
                    'location': 'Computer Lab 1',
                    'start_time': now + timedelta(days=14),
                    'end_time': now + timedelta(days=16),
                    'capacity': 40,
                    'created_by': org.id
                },
                {
                    'title': 'Freshers Welcome Party',
                    'description': 'Welcome party for new students. Games, music, free snacks, and a chance to meet seniors and faculty.',
                    'category': 'Social',
                    'location': 'Student Center Hall',
                    'start_time': now + timedelta(days=2),
                    'end_time': now + timedelta(days=2, hours=4),
                    'capacity': 200,
                    'created_by': admin.id
                },
            ]

            for ed in events_data:
                e = Event(**ed)
                db.session.add(e)

            db.session.commit()
            print("Database initialized with sample data.")


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
