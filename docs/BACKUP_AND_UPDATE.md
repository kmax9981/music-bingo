# Backing up, restoring and updating

Everything you would lose is in two places, both in Docker volumes:

| What | Where | How to back it up |
| --- | --- | --- |
| The database: accounts, games, players, saved playlists, events, settings | the `bingo-db` volume (the `db` container) | `pg_dump`, below |
| The cookie secret (signs logins **and the check codes on printed paper cards**) | the `bingo-data` volume, file `/data/cookie_secret` — or `COOKIE_SECRET` in `.env` if you set it | copy the file, or keep `.env` |

Run these in the folder that has `docker-compose.yml`.

## Back up

```bash
docker compose exec -T db pg_dump -U bingo bingo | gzip > bingo-backup-$(date +%F).sql.gz
docker compose cp app:/data/cookie_secret ./cookie_secret.backup     # skip this if COOKIE_SECRET is in your .env
```

Keep both files, and `.env`, somewhere safe and off the server. The database backup holds password hashes, player names and your
Spotify client secret, and the cookie secret signs logins, so treat them as private. Back up before every update.

**Why the cookie secret matters:** if you lose it, nobody stays logged in, and **paper cards you already printed stop passing
their check codes** (the cards themselves still work, but the host can no longer verify a bingo from the code). If you print
cards, set `COOKIE_SECRET=...` (a long random string) in `.env` before the first start so it is always in your own backups.

## Restore (a new server, or after a loss)

1. Get the files back: this folder, your `.env`, the database backup and the cookie secret backup.
2. Start only the database, and let the app wait:
   ```bash
   docker compose up -d db
   ```
3. Load the backup into the (empty) database:
   ```bash
   gunzip -c bingo-backup-2026-10-27.sql.gz | docker compose exec -T db psql -U bingo -d bingo
   ```
4. Put the cookie secret back **before the app starts** (skip this step if it is in `.env`):
   ```bash
   docker compose up --no-start app
   docker compose cp ./cookie_secret.backup app:/data/cookie_secret
   docker compose run --rm -u root --entrypoint chown app bingo /data/cookie_secret
   ```
   The last line gives the copied file to the app's own user; without it the app cannot read the file and stops with a message
   that says so.
5. Start everything: `docker compose up -d`. Log in with your old accounts; database changes for a newer version are applied
   automatically when the app starts.

## Update

```bash
git pull            # or download the new files
./run.sh            # pulls the new image (or builds it from this folder) and restarts; your data stays
```

The app applies its own database changes at start-up and records each in a `schema_migrations` table, so an update never runs
a change twice. To see which version is running, open the Admin page (menu, top right) or `docker compose logs app | grep "Music Bingo"`.
If an update goes wrong, restore your backup and start the previous version (`git checkout <previous tag>` then `./run.sh`).
