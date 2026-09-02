# Isolated server deployment

The production layout intentionally does not reuse the older `/opt/harness`
deployment:

- source: `/opt/alpaca-hack`
- secrets: `/etc/alpaca-hack/alpaca-hack.env` (`0600`)
- user: `alpaca-hack`
- official Alpaca MCP server: `127.0.0.1:8100` (`alpaca-hack-alpaca-mcp`,
  `venv/bin/pip install alpaca-mcp-server` once)
- research MCP: `127.0.0.1:8120`
- dashboard: `127.0.0.1:8130`
- isolated TrueForge: `127.0.0.1:8890`
- services: `alpaca-hack-alpaca-mcp`, `alpaca-hack-research`, `alpaca-hack-trueforge`,
  `alpaca-hack-dashboard`, and `alpaca-hack-runner`
- after any change to `mandate/agent/src/createAgent.ts` or the critic/operator
  agents, run `cd /opt/alpaca-hack/mandate/agent && npm run apply` with the
  service environment, otherwise TrueForge answers `Agent not found`
- Alpaca HTTP/WebSocket traffic uses the configured external
  `ALPACA_PROXY_URL`; no service from `/opt/harness` is reused

The dashboard and TrueForge stay loopback-only. The preferred public endpoint
is the dedicated public host from `deploy/nginx/alpaca.miposts.com.conf`:
`https://alpaca.miposts.com/`. Build it with the default `/` Vite base. The
legacy shared-host fallback remains available in `alpaca-hack.locations.conf`.

Without nginx, this tunnel exposes the read-only dashboard shell only; the
embedded Operator Fork also needs `/api/v1/*` routed to TrueForge on 8890.

```sh
ssh -L 8130:127.0.0.1:8130 root@SERVER
```

Then open `http://127.0.0.1:8130` locally.

Install and start in dependency order:

```sh
cd /opt/alpaca-hack/mandate/trueforge && npm ci --omit=dev
cd /opt/alpaca-hack/mandate/agent && npm ci
cd /opt/alpaca-hack/mandate/app && npm ci && npm run build
/opt/alpaca-hack/venv/bin/pip install -e /opt/alpaca-hack/mandate/research
/opt/alpaca-hack/venv/bin/pip install -e /opt/alpaca-hack/mandate/control-plane
/opt/alpaca-hack/venv/bin/pip install alpaca-mcp-server
systemctl enable --now alpaca-hack-alpaca-mcp alpaca-hack-research alpaca-hack-trueforge
curl --fail http://127.0.0.1:8100/mcp
curl --fail http://127.0.0.1:8890/api/v1/agents
cd /opt/alpaca-hack/mandate/agent && npm run apply
systemctl restart alpaca-hack-dashboard alpaca-hack-runner
```

Before starting the runner, verify the Alpaca MCP handshake and read-only tool
list on 8100, `GET http://127.0.0.1:8890/api/v1/agents`,
`GET http://127.0.0.1:8130/api/snapshot`, the Alpaca paper endpoint, and the
configured external Alpaca proxy. Never expose ports 8120, 8130, or 8890
directly. The dedicated `alpaca.miposts.com` vhost is intentionally public for
the hackathon demo, including its chat API; do not reuse that policy for a live
broker account.
