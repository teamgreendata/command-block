# command-block backlog

- [ ] Re-run the plan's Part A checks **on webnode** (network name, restart policy, `.env`, port 8300 free, log path) — the 2026-08-02 pass ran on the K12's stale soak copy by mistake
- [ ] Deploy on webnode (build plan Part F): clone to `/opt/stacks/command-block`, write `.env`, `docker compose up -d --build`
- [ ] Run Part G acceptance tests against the real server (incl. the restart button)
- [ ] Homepage tile (K12's Homepage): `href: http://webnode:8300`, any widget `url:` by LAN IP `10.0.0.64`
- [ ] Uptime Kuma (lifeboat): HTTP monitor on `http://10.0.0.64:8300/healthz`
- [ ] network-reference v1_3 bump: webnode `:8300` = command-block
- [ ] Vaultwarden entry for the RCON password (referenced by two `.env` files on webnode)
