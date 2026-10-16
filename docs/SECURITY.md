# Security and reliability

## Authentication

* Django session authentication for the SPA (HttpOnly session cookie, `SameSite=Lax`, `Secure` when served over
  HTTPS, 8-hour lifetime). The SPA and API share one origin, so no tokens are stored in the browser.
* CSRF protection on all unsafe requests (`X-CSRFToken` header from the CSRF cookie; trusted origins configured
  via `DJANGO_CSRF_TRUSTED_ORIGINS`). Covered by `test_csrf_enforced_for_session_writes`.
* Login is rate limited (`PLANTOPS_LOGIN_RATE`, default 10/min per client) and returns the same message for
  unknown users, wrong passwords and inactive accounts. Failed logins are audited.
* Passwords use Django's PBKDF2 hasher and validators (minimum length 10, common/numeric/similarity checks).
* **BI tokens** (DRF `Token`) are issued only to roles with `bi.access`, shown once, rotatable and revocable, and are
  accepted **only** by the read-only `/api/bi/` endpoints (`test_bi_api_token_scope`).

## Authorisation

* Every endpoint declares the permission for each action; unmapped actions are denied (closed by default).
* Permissions come from one matrix ([PERMISSIONS.md](PERMISSIONS.md)); the frontend hides controls but the API
  re-checks every request (tested across roles in `test_role_matrix_enforced_server_side` and the e2e suite).
* Object-level rules: operations officers report only on their assigned units; supervisors review only their
  units; no one approves or verifies their own work; management sees approved operational data only; employee
  contact details and pay rates are visible only to administrators and supervisors; alerts are filtered by the
  rule's audience.
* Users cannot change their own role (the profile endpoint accepts only name and theme); administrators cannot
  change their own role or deactivate themselves; role changes are audited as security events.

## Input handling

* Serializer validation for shape; service-layer validation for business rules; database constraints as the last
  line. Errors return `{detail, errors}` without stack traces; integrity errors return HTTP 409 without SQL.
* File uploads: extension allow-list (pdf, png, jpg, txt, csv, xlsx), 5 MB limit, magic-number check for binary
  types, UTF-8 check for text, random storage names, download through an authorised endpoint, view/edit rights
  derived from the parent record.
* Spreadsheet exports neutralise formula injection (cells starting with `= + - @` are prefixed with `'`).
* BI dataset names are whitelisted before being used in SQL; all other SQL uses parameters.

## Secrets and configuration

* No secrets in source control. `DJANGO_SECRET_KEY` is mandatory when `DJANGO_DEBUG=false`; the development
  fallback key is used only with debug or tests. `.env` is git-ignored; `.env.example` documents every variable.
* The demo password comes from `PLANTOPS_DEMO_PASSWORD`; demo accounts are created only by the seeder, which
  refuses to run against non-demo data.
* Logging redacts `password=`, `token=`, `sessionid=`, `csrftoken=` and `authorization=` values.
* Security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`;
  HSTS and SSL redirect configurable for production.

## Production checklist

1. `DJANGO_DEBUG=false`, strong `DJANGO_SECRET_KEY`, correct `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
2. Serve over HTTPS behind a reverse proxy that sets `X-Forwarded-Proto`; keep `DJANGO_SECURE_COOKIES=true`;
   set `DJANGO_HSTS_SECONDS`.
3. `PLANTOPS_DEMO_MODE=false` (disables `seed_demo --reset`).
4. Database user with only the privileges the app needs; a separate read-only role for Power BI
   (`docs/powerbi/create_bi_reader.sql`).
5. Schedule `evaluate_alerts` and `generate_pm_work_orders`.
6. Store media (attachments) on durable storage and include it in backups.

## Backup and restore

```bash
# Daily logical backup (custom format, compressed); keep several generations off-site
pg_dump --format=custom --no-owner --file=plantops_$(date +%F).dump "$DATABASE"
tar czf plantops_media_$(date +%F).tgz -C backend media

# Restore into an empty database
createdb plantops_restore
pg_restore --no-owner --dbname=plantops_restore plantops_2026-10-15.dump
cd backend && POSTGRES_DB=plantops_restore python manage.py migrate   # no-op if already current
python manage.py bi_reconcile                                         # sanity check KPIs vs BI views
```
On Windows use the same `pg_dump` / `pg_restore` binaries from the PostgreSQL installation (`bin` folder).
Test restores periodically; the `bi` schema is recreated by migrations if it is not included.
