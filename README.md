# UniEvents — University Event Management System

A full-stack web application for managing university events. Students can browse and register for events; organizers can create and manage events; admins have full control.

## Features

- **User roles**: Student, Organizer, Admin
- **Event management**: Create, edit, delete events
- **Registration system**: Register / unregister with capacity limits
- **Search & filters**: By category, status, keyword
- **Admin dashboard**: Manage users and events
- **Responsive UI**: Works on mobile and desktop
- **Sample data**: Ready to explore immediately

## Tech Stack

| Layer     | Technology              |
|-----------|-------------------------|
| Frontend  | HTML5, CSS3, Bootstrap 5, Vanilla JS |
| Backend   | Python Flask            |
| Database  | SQLite                  |
| Auth      | Session-based (Werkzeug hashing) |

## Project Structure

```
university-event-system/
├── backend/
│   ├── app.py              # Main Flask application
│   └── requirements.txt
├── frontend/
│   ├── css/style.css
│   └── js/main.js
├── templates/              # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── events.html
│   ├── event_detail.html
│   ├── create_event.html
│   ├── edit_event.html
│   ├── my_events.html
│   ├── calendar.html
│   ├── login.html
│   ├── register.html
│   └── admin.html
├── events.db               # SQLite database (created on first run; not tracked)
└── README.md
```

## Quick Start

### 1. Install dependencies

```bash
cd university-event-system/backend
pip install -r requirements.txt
```

### 2. Configure first-run secrets

The sample accounts are seeded only when the database is empty. Set strong,
private passwords before the first run. Keep these values in your environment
or an untracked `.env` file; never commit them.

PowerShell:

```powershell
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
$env:SEED_ADMIN_PASSWORD = "<your-strong-admin-password>"
$env:SEED_ORGANIZER_PASSWORD = "<your-strong-organizer-password>"
$env:SEED_STUDENT_PASSWORD = "<your-strong-student-password>"
```

Set a stable `SECRET_KEY` in your deployment environment so sessions remain
valid across application restarts.

### 3. Run the server

```bash
python app.py
```

The app starts at: **http://127.0.0.1:5000**

Seeded usernames are `admin`, `organizer1`, `student1`, and `student2`;
passwords are the values configured above.

## How to Use

1. **Browse events** — Home page shows upcoming events; Events page has filters
2. **Register** — Login as student → open an event → click Register
3. **Create event** — Login as organizer or admin → Create Event
4. **Admin panel** — Login as admin → Admin menu to manage users & events

## API / Routes Overview

| Route                    | Method | Description                |
|--------------------------|--------|----------------------------|
| `/`                      | GET    | Home page                  |
| `/events`                | GET    | Event listing + filters    |
| `/event/<id>`            | GET    | Event details              |
| `/register/<id>`         | POST   | Register for event         |
| `/unregister/<id>`       | POST   | Unregister                 |
| `/create-event`          | GET/POST | Create new event         |
| `/edit-event/<id>`       | GET/POST | Edit event               |
| `/my-events`             | GET    | User's registrations       |
| `/login` `/register`     | GET/POST | Auth                     |
| `/admin`                 | GET    | Admin dashboard            |

## Notes

- Database file `events.db` is created automatically on first run
- Sample events and users are seeded if the database is empty
- Event status (upcoming / ongoing / completed) updates automatically based on time
- Passwords are hashed with Werkzeug; never stored in plain text

## Implemented Features

- Email notifications (configure SMTP with environment variables)
- Calendar view powered by FullCalendar
- Event image uploads and image URLs
- Automatic waitlist promotion
- QR code tickets and organizer check-in
- JSON REST API for mobile applications

---

Built for university course / portfolio project use.
