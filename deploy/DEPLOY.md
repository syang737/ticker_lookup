# Deploying to Lightsail

Runs beside the tee time watcher on the same instance: its own subdomain,
its own systemd service on port 8001, the same Caddy in front.

## 1. DNS

Porkbun → the domain → DNS: add an `A` record, host `prices` (or whatever
subdomain you want), answer = the instance's static IP -- the same IP the
other subdomains point to. Ports 80 and 443 are already open.

## 2. Code and secrets

```bash
cd ~
git clone https://github.com/syang737/ticker_lookup.git
cd ticker_lookup
python3 -m venv .venv
.venv/bin/pip install .
cp .env.example .env && chmod 600 .env
nano .env
```

Fill in `APP_PASSWORD` (long -- this is on the internet), `SECRET_KEY`
(`python3 -c "import secrets; print(secrets.token_hex(32))"`),
`MASSIVE_API_KEY`, `OPENFIGI_API_KEY`, and set **`SECURE_COOKIE=true`**.

## 3. Service

```bash
sudo cp deploy/ticker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ticker
curl -sI http://127.0.0.1:8001/login    # HTTP/1.1 200 OK
```

## 4. Caddy

Each app gets its own file under `/etc/caddy/sites/`, and the main Caddyfile
only imports them, so one app's deploy cannot remove another's site. The tee
time watcher's `setup.sh` sets that layout up, so update it first -- this
moves its own site out of the main Caddyfile:

```bash
cd ~/tee_time_scraper && git pull && ./deploy/setup.sh golf.potpourri.lol
grep -x 'import sites/\*.caddy' /etc/caddy/Caddyfile    # should print the line
```

Then add this site (edit the hostname first if it is not prices.potpourri.lol):

```bash
cd ~/ticker_lookup
sudo cp deploy/ticker.caddy /etc/caddy/sites/ticker.caddy
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  && sudo systemctl reload caddy
```

Caddy fetches the certificate on the first request; give DNS a few minutes
to propagate first.

## Updating

```bash
cd ~/ticker_lookup && git pull
.venv/bin/pip install .
sudo systemctl restart ticker
```

`.env` is read when the service starts; restart after editing it too.

## When it is not working

- **502** -- the app is down: `journalctl -u ticker -n 50`. A missing
  `APP_PASSWORD` or `MASSIVE_API_KEY` stops it at startup.
- **Signed out right after signing in** -- `SECURE_COOKIE=true` over plain
  HTTP; the certificate has not been issued yet.
- **Certificate errors** -- the `A` record does not point here yet:
  `dig +short prices.potpourri.lol`.
