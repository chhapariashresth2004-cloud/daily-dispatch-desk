# Daily Dispatch Desk

Role-based internal dispatch workflow app for a warehouse / billing / transport team.

## What Phase 1 now does

- Replaces the handwritten daily dispatch register with structured jobs
- Uses separate dashboards for:
  - Dispatcher
  - Reviewer
  - Admin
- Keeps the real workflow strict:
  - Bill uploader chooses the route
  - Dispatcher packs goods, enters packing breakup, uploads packing photo, submits for review
  - Reviewer checks the packing proof, enters delivery / transport details, marks sent to dispatch
  - Reviewer uploads bilty proof and completes the dispatch afterward when transport is used
- Stores separate counts for:
  - `order_case_count`
  - auto-calculated total packages
  - `bilty_package_count`
- Requires bilty package count to match final package count before completion
- Separates:
  - `delivery_partner_name`
  - `transport_mode`
  - `transport_name`
- Uses optional bilty reference instead of mandatory bilty number
- Includes:
  - route batching foundation
  - activity logs
  - productivity timestamps
  - AI-ready placeholder fields
  - WhatsApp-ready placeholder fields
  - admin edit / user / route controls
  - mobile-first layouts

## Current status flow

1. Ready  
2. Assigned  
3. Packing  
4. Submitted for Review  
5. Needs Correction  
6. Approved by Reviewer  
7. Dispatch Pending  
8. Dispatched / Sent to Dispatch  
9. Completed  
10. Cancelled

## Main validation rules

- Dispatcher cannot submit without:
  - packing photo
  - packing breakup
  - shortage explanation when packed cases do not match order cases
- Reviewer cannot dispatch without:
  - delivery partner name
  - transport mode
  - transport name when mode is `Transport`
- Reviewer cannot complete transport dispatch without:
  - bilty photo
  - bilty package count matching total packages
- Duplicate detection uses invoice + party + bill date so separate parties with the same visible invoice number are not incorrectly blocked

## Default local logins

Temporary local credentials for testing only:

| Role | Login | Password |
| --- | --- | --- |
| Admin | `admin` | `admin123` |
| Reviewer | `reviewer1` | `reviewer123` |
| Dispatcher | `dispatcher1` | `dispatcher123` |

## Run locally

```powershell
& 'C:\Users\Shresth Chhaparia\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' server.py
```

Open:

```text
http://127.0.0.1:8000
```

Same-Wi-Fi mobile access while this computer is running:

```text
http://192.168.29.78:8000
```

The app now includes a web-app manifest so it can be added to a mobile home screen after deployment or same-network access.

## Storage

- Main database: `data/dispatches.db`
- Bills: `uploads/bills`
- Packing photos: `uploads/product-photos`
- Bilty photos: `uploads/bilty-photos`

The app also supports isolated demo runs with:

- `DISPATCH_DATA_DIR`
- `DISPATCH_UPLOAD_DIR`
- `DISPATCH_DB_PATH`
- `DISPATCH_PORT`

## Future-ready foundations

Phase 1 does **not** implement AI or WhatsApp automation yet.

Already prepared for Phase 2:

- AI photo / bilty analysis fields
- WhatsApp delivery status fields
- productivity timestamps
- transporter / delivery-partner reporting
- route batching

The reviewer remains the final human decision maker.

## Production hardening still needed before real multi-device rollout

- Change default passwords
- Add HTTPS and deployment hosting
- Add scheduled backups
- Move files to cloud object storage
- Add user password reset flow
- Add richer exports and filters
- Add monitoring and operational alerts
