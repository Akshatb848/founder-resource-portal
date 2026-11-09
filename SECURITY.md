# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability** (private security advisory) on
this repository, or contact the author through the GitHub profile [@Akshatb848](https://github.com/Akshatb848).
I aim to reply within a week.

## What this repository contains

- Application code and **fictional demo data only**. No real companies, founders, investors, staff, email
  addresses or documents are included.
- No secrets. Every password in config examples, `docker-compose.yml` and CI is a placeholder (`change-me`)
  for a throw-away local or CI database. Seeded demo accounts use the public demo password `demo1234`;
  never seed demo data into a database that real people use.

## Security design (summary)

- Only the built frontend (`dist/`) is served as static files; source, `backend/.env`, docs and `.git` answer 404.
- Sessions are database-backed bearer tokens (revocable, multi-device); passwords are hashed with bcrypt.
- Failed sign-ins are rate-limited and locked out for a period; every sign-in failure and admin action is audited.
- Every API route checks a named permission (not a role), scoped to "all" or "assigned" companies.
- Responses carry security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, `no-store`).
- Uploads are size-limited; spreadsheet parsing uses `defusedxml` and refuses zip bombs.
- The optional RSS reader accepts only `https` feeds and refuses private/internal addresses (SSRF guard). It is off by default.
- Demo seeding and the demo reset refuse to run against a database marked as holding real data.

## If you deploy it

Set a strong `PG_PASSWORD`, run behind HTTPS, keep `APP_ENV=production` (hides the API docs), configure SMTP
before enabling one-time-code sign-in, and do not load the demo seed.
