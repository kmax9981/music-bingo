# Putting Music Bingo on the internet with HTTPS

Spotify only signs in over `https://` (the one exception is `http://127.0.0.1`), phones expect a normal web address, and the
music player in the browser needs a secure page. So for anything beyond trying it on your own computer, put a **reverse proxy**
in front of the app. You need a domain name that points at your server (an `A`/`AAAA` record), and ports 80 and 443 reachable.

Whichever you pick:

- Tell the app its public address on the setup screen (or **Admin → App settings**), for example `https://bingo.example.com`,
  and register `https://bingo.example.com/auth/spotify/callback` as a redirect URI in your Spotify app.
- Do **not** leave the app's own port open to the internet. The app trusts the visitor address a proxy passes along
  (`TRUST_PROXY_HEADERS=true`, the default) to rate-limit logins; a port that bypasses the proxy lets someone fake it.
  With the Caddy setup below the app has no published port at all.
- The proxy must pass **WebSockets** (the live game updates use them) and the usual `X-Forwarded-Proto` / `X-Forwarded-Host` /
  `X-Forwarded-For` headers. Caddy does this by itself; nginx needs the lines shown.

## Caddy (recommended: it gets and renews the certificate for you)

Next to `docker-compose.yml`, make a file called `docker-compose.override.yml` (Compose reads it automatically):

```yaml
services:
  app:
    ports: !reset []          # the app is reachable only through Caddy
  https:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on: [app]
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
volumes:
  caddy-data:
```

and a file called `Caddyfile`:

```
bingo.example.com {
	reverse_proxy app:5000
}
```

Replace `bingo.example.com` with your domain, then `docker compose up -d`. The first request gets the certificate.

## nginx (already have one running on the host)

Keep the app on the host's loopback only, so nothing but nginx can reach it: put this in `docker-compose.override.yml`

```yaml
services:
  app:
    ports: !override
      - "127.0.0.1:5000:5000"
```

and in your nginx site (with certificates from certbot or similar):

```nginx
server {
    listen 443 ssl http2;
    server_name bingo.example.com;
    # ssl_certificate / ssl_certificate_key ...

    client_max_body_size 6m;                      # event logos go up to 5 MB

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;   # WebSockets
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;   # not $proxy_add_x_forwarded_for: do not trust what the visitor sent
        proxy_read_timeout 3600s;
    }
}
```

## Cloudflare Tunnel (no open ports at all, even behind a home router)

In the Cloudflare dashboard (Zero Trust → Networks → Tunnels) create a tunnel and add a public hostname
`bingo.example.com` pointing to `http://app:5000`. Copy the tunnel token into `.env` as `TUNNEL_TOKEN=...`, then in
`docker-compose.override.yml`:

```yaml
services:
  app:
    ports: !reset []
  tunnel:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${TUNNEL_TOKEN}
    depends_on: [app]
```

Cloudflare passes WebSockets and the visitor's address on its own.

## Check it

Open `https://bingo.example.com`, log in, create a game and open the join link on a phone on mobile data (not your Wi-Fi). If
the live updates do not arrive (the player list does not fill in, the card does not react to songs), the proxy is not passing
WebSockets.
