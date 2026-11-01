# Locked out? Reset a host password

There is no web page or URL for this: it is a command you run on the server, so it only works for someone who already
controls the server and there is no secret to protect or leak.

```bash
# new random password for an existing user (shown once)
docker compose exec app python -m app.reset_password USERNAME

# the account doesn't exist (or you lost every account): create it as an admin
docker compose exec app python -m app.reset_password USERNAME --create
```

Run it in the folder with `docker-compose.yml`. (If you start the containers differently, use `docker exec -it <container name> ...`.)
Log in with the printed password: you are asked to choose your own password straight away.

## First run

A brand-new install has no accounts. Open the app in a browser and it shows the **setup screen**, where you choose the admin
account's username and password, the public address and your Spotify developer app. Do this before you make the app
reachable from the internet: until the account exists, whoever opens the page first can create it.

Unattended installs can set `HOST_ADMIN_PASSWORD` in `.env` instead: the admin account is then created from it on the
first start and the setup screen is skipped (the address and Spotify details can still be set in the app).
