# PulseNotify

PulseNotify is a Django REST Framework backend for flight-price alerts. Users register, create route and threshold alerts, and list or deactivate their own alerts. Celery Beat schedules a price check every 60 seconds; a Celery worker calls the project's mock price endpoint and writes a notification log when a price meets an alert threshold.

## Technology

- Python 3.12 or newer
- Django, Django REST Framework and SimpleJWT
- PostgreSQL and Redis, started with Docker Compose
- Celery worker and Celery Beat
- Postman for manual API checks

## Prerequisites

Install Python, Docker Desktop (and start it), and Postman. Run all commands below from the project root in Windows PowerShell.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once in PowerShell and activate again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Create the local environment file **before** starting Docker Compose:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set a private, long `SECRET_KEY` and a local `DB_PASSWORD`. The same database name, username, password and port are consumed by Django and Docker Compose. `.env` contains local secrets and must not be committed; `.env.example` contains placeholders and should be submitted.

Start PostgreSQL and Redis, install the pinned packages, and apply the committed migrations:

```powershell
docker compose up -d
docker compose ps
python -m pip install -r requirements.txt
python manage.py check
python manage.py migrate
```

The initial migration is already included. `makemigrations` is not needed for a normal setup; use this command to check for uncommitted model changes:

```powershell
python manage.py makemigrations --check --dry-run
```

Optionally create a Django admin-site account:

```powershell
python manage.py createsuperuser
```

The Django superuser/staff flags are not the PulseNotify API admin role. To access the summary API, the user's separate `UserProfile.role` must be `admin`.

## Run the application

Start each process in its own PowerShell terminal from the project root. Activate `.venv` in each terminal.

**Terminal 1 — Django API**

```powershell
python manage.py runserver
```

**Terminal 2 — Celery worker**

```powershell
celery -A config worker --loglevel=info --pool=solo
```

**Terminal 3 — Celery Beat**

```powershell
celery -A config beat --loglevel=info
```

The API base URL is `http://127.0.0.1:8000`. The Django server must be running so the worker can call the mock price feed. Beat schedules `pulse.tasks.check_prices` every 60 seconds; the worker executes it and the queued notification task.

## API operations

All request examples use `http://127.0.0.1:8000` as the base URL. The protected examples require the JWT access token returned from registration or login, sent as `Authorization: Bearer <access-token>`.

Example PowerShell requests for the protected read/deactivate operations and the public price feed:

```powershell
$baseUrl = "http://127.0.0.1:8000"
$token = "<access-token-from-register-or-login>"
$headers = @{ Authorization = "Bearer $token" }

# GET /api/alerts/ — JWT required
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/alerts/" -Headers $headers

# DELETE /api/alerts/<id>/ — JWT required
Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/alerts/1/" -Headers $headers

# GET /api/flights/price/?route=DEL-BOM — public
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/flights/price/?route=DEL-BOM"

# GET /api/admin/summary/ — JWT required; the account's profile role must be admin
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/admin/summary/" -Headers $headers
```

### 1. Register — public

`POST /api/auth/register/`

```json
{
  "username": "alice",
  "password": "securepass123",
  "email": "alice@example.com"
}
```

Returns `201` with `username`, `access`, and `role` (`user`). Any `role` supplied by the client is ignored; a new profile is created by the User `post_save` signal.

### 2. Login — public

`POST /api/auth/login/`

```json
{
  "username": "alice",
  "password": "securepass123"
}
```

Returns `200` with a fresh access token and profile role. Invalid credentials return `401`.

### 3. Create an alert — JWT required

`POST /api/alerts/`

```json
{
  "origin": "DEL",
  "destination": "BOM",
  "threshold_price": "4500.00"
}
```

Returns `201`. The authenticated user is set by the server; the request body cannot select an owner.

### 4. List my alerts — JWT required

`GET /api/alerts/`

Returns `200` and an array containing only the logged-in user's alerts. No alerts returns an empty array (`[]`).

### 5. Deactivate my alert — JWT required

`DELETE /api/alerts/<id>/`

Example: `DELETE /api/alerts/1/`

Returns `200` and `{"status":"inactive"}`. The row is retained. A missing alert or another user's alert returns `404`.

### 6. Read the mock flight price — public

`GET /api/flights/price/?route=DEL-BOM`

Returns `200`, for example `{"route":"DEL-BOM","price":4200}`. The price is a random integer in that route's configured range. Supported routes are `DEL-BOM`, `BLR-HYD`, `DEL-BLR`, and `BOM-GOA`; an unsupported route returns `404`.

### 7. Read the admin summary — JWT and admin profile role required

`GET /api/admin/summary/`

Returns `200` with alert counts, notification count, and up to five grouped top routes. A normal user receives `403`. For local testing, use pgAdmin or another database client to set that user's `pulse_userprofile.role` to `admin`, then log in again and use the returned access token. Django's `is_staff` and `is_superuser` do not grant this API role.

## Background tasks

`check_prices` reads distinct routes with active alerts and calls the configured `FLIGHT_PRICE_FEED_URL` using `requests.get()` with a timeout. When a price is at or below an alert's Decimal threshold, it queues `send_notification.delay(...)`. The notification task creates a `NotificationLog` and changes the alert status to `triggered`. It ignores an alert that has already been triggered, preventing repeated task delivery from creating duplicate logs.

The feed URL defaults to `http://127.0.0.1:8000/api/flights/price/` and can be overridden in `.env`. If the Django server uses a different address or port, set `FLIGHT_PRICE_FEED_URL` to that server's reachable URL.

## Tests

With the configured PostgreSQL service running, run:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

The tests cover threshold comparisons, notification logging and repeat delivery, user-profile creation, authentication, alert ownership and access, mock prices, and admin permissions.

## Postman

Import `PulseNotify.postman_collection.json` into Postman. Run the collection in order; the successful registration request generates a unique username and stores its token for the protected user scenarios.

Two scenarios require a separate admin setup:

1. To exercise **Another User's Alert**, create an alert using a second account and put its ID in the collection variable `foreign_alert_id`. Use the first account's token for the request.
2. To exercise **Admin Summary — Admin Success**, set one account's `UserProfile.role` to `admin` in the database, log in as that account, and paste its access token into `admin_access_token`. The normal-user summary scenario uses the ordinary `access_token`.

The collection includes assertions for expected status codes and key response fields. Actual Postman results are only verified when the collection is run against a running local application.

## Design decisions

- Django's built-in `User` is retained, with a separate one-to-one `UserProfile`; a `post_save` signal creates the default user-role profile for all newly created users.
- API alerts are scoped to the authenticated user. Deactivation updates status rather than deleting the record, preserving alert history.
- PostgreSQL aggregation computes summary counts and grouped routes. Celery separates scheduled price checks from asynchronous notification logging so API requests do not wait for background work.
- The mock feed is an endpoint in this project rather than a third-party flight API, keeping the backend-to-backend `requests.get()` flow testable without external credentials.
