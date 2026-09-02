# Isolated server deployment

The production layout intentionally does not reuse the older `/opt/harness`
deployment:

- source: `/opt/alpaca-hack`
- secrets: `/etc/alpaca-hack/alpaca-hack.env` (`0600`)
- user: `alpaca-hack`
- research MCP: `127.0.0.1:8120`
- dashboard: `127.0.0.1:8130`
- isolated TrueForge: `127.0.0.1:8890`
- services: `alpaca-hack-research`, `alpaca-hack-trueforge`,
  `alpaca-hack-dashboard`, and `alpaca-hack-runner`
- Alpaca HTTP/WebSocket traffic uses the configured external
  `ALPACA_PROXY_URL`; no service from `/opt/harness` is reused

The dashboard and TrueForge stay loopback-only. On the shared authenticated
nginx host, include `deploy/nginx/alpaca-hack.locations.conf` in the HTTPS
`server` block and build the UI with `VITE_BASE_PATH=/alpaca/`. The operator
URL is then `https://harn.miposts.com/alpaca/`.

Without nginx, reach the dashboard safely with:

```sh
ssh -L 8130:127.0.0.1:8130 root@SERVER
```

Then open `http://127.0.0.1:8130` locally.

Install and start in dependency order:

```sh
cd /opt/alpaca-hack/mandate/trueforge && npm ci --omit=dev
cd /opt/alpaca-hack/mandate/agent && npm ci
cd /opt/alpaca-hack/mandate/app && npm ci && VITE_BASE_PATH=/alpaca/ npm run build
systemctl enable --now alpaca-hack-research alpaca-hack-trueforge
curl --fail http://127.0.0.1:8890/api/v1/agents
cd /opt/alpaca-hack/mandate/agent && npm run apply
systemctl restart alpaca-hack-dashboard alpaca-hack-runner
```

Before starting the runner, verify `GET http://127.0.0.1:8890/api/v1/agents`,
`GET http://127.0.0.1:8130/api/snapshot`, the Alpaca paper endpoint, and the
configured external Alpaca proxy. Never expose ports 8120, 8130, or 8890
directly.
