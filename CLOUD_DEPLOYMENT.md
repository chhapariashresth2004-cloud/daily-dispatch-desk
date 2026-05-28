# Daily Dispatch Desk cloud deployment

This app is now prepared for a live cloud pilot so it can run on phones/computers from different Wi-Fi networks.

## Recommended pilot setup

Use a Python web service with a persistent disk.

The app stores:

- database: `/var/data/dispatches.db`
- bill PDFs/photos: `/var/data/uploads`

The included `render.yaml` configures:

- Python app service
- persistent disk
- environment variables
- start command

## Environment variables

```text
DISPATCH_DATA_DIR=/var/data
DISPATCH_UPLOAD_DIR=/var/data/uploads
DISPATCH_DB_PATH=/var/data/dispatches.db
```

The cloud platform supplies `PORT`; `server.py` now supports that automatically.

## Default logins

After first deploy, the app seeds default users:

- Admin: `admin` / `admin123`
- Reviewer: `reviewer1` / `reviewer123`
- Dispatcher: `dispatcher1` / `dispatcher123`

Immediately change these in **Admin → Users** after deployment.

## Important pilot notes

This pilot uses one cloud server with a persistent disk. It is good for a small team pilot and 5 devices.

## Render setup

Create a new Render **Web Service** from the GitHub repo.

Use:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: python server.py
```

Add a persistent disk:

```text
Name: dispatch-data
Mount path: /var/data
Size: 5 GB
```

Do not deploy this app on a free/sleeping service for real dispatch work.

Before long-term heavy use, the stronger production setup should be:

- PostgreSQL database
- object storage for bills/photos
- scheduled backups
- domain name
- monitoring
