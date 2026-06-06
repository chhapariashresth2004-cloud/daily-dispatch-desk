# Daily Dispatch Desk cloud deployment

This app is prepared for a live cloud pilot so it can run on phones/computers from different Wi-Fi networks.

## Recommended monthly pilot setup

Use Render monthly billing, not yearly.

Recommended setup:

```text
Workspace: Hobby
Web service: Starter
Persistent disk: 50 GB
Disk mount path: /var/data
```

Estimated monthly cost:

```text
Starter service: $7/month
50 GB disk: $12.50/month
Total: about $19.50/month
Approx INR: ₹1,850–₹2,000/month
```

You can stop anytime by suspending/deleting the Render service. Do not delete the disk unless you have downloaded a backup, because the disk contains business data and photos.

## Where data is stored

The app stores:

```text
Database: /var/data/dispatches.db
Bill PDFs/photos: /var/data/uploads
```

The included `render.yaml` configures:

- Python web service
- Starter plan
- 50 GB persistent disk
- storage environment variables
- start command

## Required environment variables

```text
DISPATCH_DATA_DIR=/var/data
DISPATCH_UPLOAD_DIR=/var/data/uploads
DISPATCH_DB_PATH=/var/data/dispatches.db
```

Render supplies `PORT`; `server.py` uses it automatically.

## Default logins

After first deploy, the app seeds default users:

- Admin: `admin` / `admin123`
- Reviewer: `reviewer1` / `reviewer123`
- Dispatcher: `dispatcher1` / `dispatcher123`

Immediately change these in **Admin → Users** after deployment.

## Render setup steps

Create or update the Render **Web Service** from the GitHub repo.

Use:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: python server.py
Instance type: Starter
```

Add persistent disk:

```text
Name: dispatch-data
Mount path: /var/data
Size: 50 GB
```

If using the Blueprint from `render.yaml`, these settings are already declared in the file.

## Confirm cloud storage is active

After deploy, open:

```text
https://daily-dispatch-desk.onrender.com/api/health
```

Correct result must show:

```text
dataDir: /var/data
uploadDir: /var/data/uploads
dbPath: /var/data/dispatches.db
```

If it shows this instead, storage is NOT safe:

```text
/opt/render/project/src/data
```

Do not use real business data until `/var/data` is active.

## Backup habit during pilot

Before big changes or redeploys:

1. Login as Admin.
2. Export bills/data from the app.
3. Keep a copy locally.

Render disk snapshots are useful, but manual export is still safer for business records.

## Important pilot notes

This setup is good for:

- 5–10 devices
- around 50 dispatches/day
- 45–90 days data if photos are compressed

Before long-term heavy use, the stronger production setup should be:

- PostgreSQL database
- object storage for bills/photos
- scheduled backups
- domain name
- monitoring
