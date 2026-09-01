# Isolated server deployment

The production layout intentionally does not reuse the older `/opt/harness`
deployment:

- source: `/opt/alpaca-hack`
- secrets: `/etc/alpaca-hack/alpaca-hack.env` (`0600`)
- user: `alpaca-hack`
- research MCP: `127.0.0.1:8120`
- dashboard: `127.0.0.1:8130`
- services: `alpaca-hack-research`, `alpaca-hack-dashboard`, and
  `alpaca-hack-runner`
- Alpaca HTTP/WebSocket traffic uses the configured external
  `ALPACA_PROXY_URL`; no service from `/opt/harness` is reused

The dashboard stays loopback-only until a separately authenticated nginx host
is configured. Reach it safely with:

```sh
ssh -L 8130:127.0.0.1:8130 root@SERVER
```

Then open `http://127.0.0.1:8130` locally.
