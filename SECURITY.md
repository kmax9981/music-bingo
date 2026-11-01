# Security

## Reporting a problem

Please report security problems **privately**, not in a public issue. On GitHub, use the **Security** tab of this
repository and choose **Report a vulnerability**. Include what you found, how to reproduce it, and which version
(release tag or date) you ran.

This is a hobby project run by one person: there is no bounty and no guaranteed response time, but reports are read and
fixes are released as soon as they can be tested. Please give a fix time to reach people before you share details.

## What is in place

- Passwords are stored hashed (never in plain text); failed logins are rate-limited
- Changing a password logs out the account's other browsers; deleted accounts are logged out at once
- CSRF protection on every state-changing request, and a strict Content-Security-Policy (no inline scripts or styles)
- Session and CSRF cookies are signed with your `COOKIE_SECRET` and are `Secure` behind HTTPS
- A fresh install shows a setup screen where you choose the admin password;
  there is no built-in reset URL. Locked out? Use the command on the server: `docs/README_PASSWORD_RESET.md`
- Live-update sockets only accept the game's owner (host) or a player who joined it, and only from this site
- The Spotify sign-in's one-time code is kept out of the access log
- The app runs as an ordinary user inside its container, and the database is not reachable from outside the compose network
- Uploaded event logos must be real PNG or JPG files, up to 5 MB
- A Spotify client secret entered in the app (setup screen or Admin page) is stored in the database and never shown again, so
  treat database backups as secret. Setting it in `.env` instead keeps it out of the database

## If you run it yourself

- Put it behind HTTPS, and keep the `.env` file `run.sh` makes private (mode 600, never committed)
- The cookie secret is made by the app and kept in its data volume; keep that volume (changing the secret signs everyone out)
- Finish the setup screen right after the first start, before the app is reachable from the internet (until the first account exists, whoever opens it first can create it), and create separate accounts for other hosts
- Back up the database before updating, and update when new releases come out
