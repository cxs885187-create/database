# Database Server Deployment Design

## Goal

Deploy the current vocabulary database application to `82.156.102.68` and make it reachable at a public HTTP URL while keeping its SQLite data and logs on the server disk. Preserve the existing GitHub `master` branch and leave HippoArk untouched.

## Current context

- The working copy contains in-progress application changes that are part of the version to deploy. Work is isolated on local branch `codex/database-public-deploy`.
- The app is a FastAPI service with static assets under `app/static/` and an SQLite database configured through `DATABASE_PATH`.
- The local database is schema version 2 and currently contains 79 words and 3 review events. Notes are empty.
- The local `.env` contains the existing DeepSeek configuration. It must not be committed or printed; a server-only copy will be permission-restricted.
- The server is Ubuntu 24.04, has about 33 GB free disk and about 1.8 GB available memory, and already runs HippoArk and other services. A separate port is available.

## Approaches considered

1. **Direct HTTP on a dedicated port.** Run the app on port 8088 with HTTP Basic authentication and allow that port through the host firewall. This would give a stable IP URL, but a direct connection to `82.156.102.68:8088` timed out because the cloud firewall did not expose the port.
2. **Cloudflare Quick Tunnel with HTTPS (selected fallback).** Keep Uvicorn on loopback port 8088 and run an independent Quick Tunnel systemd service. This avoids changing the cloud firewall or Nginx and provides HTTPS without a domain. The generated URL is stable while the tunnel process runs and may change after a restart.
3. **A custom domain with HTTPS.** This offers a stable, trusted URL but requires a domain and DNS configuration that were not supplied.

## Design

### Application configuration and access

- Add optional `APP_USERNAME`, `APP_PASSWORD`, and `ALLOWED_HOSTS` settings. When username and password are configured, an application-wide HTTP Basic Auth middleware protects the index, static assets, API routes, and documentation. Local development remains unchanged when both credentials are unset.
- Reject startup configuration where only one of username/password is set. Compare submitted credentials with constant-time comparison and return a Basic Auth challenge for missing or incorrect credentials.
- Reject `:` in usernames because HTTP Basic uses it to separate username from password. Enforce credential invariants even when `Settings` is constructed directly, not only when loaded from `.env`.
- Keep the existing local host allowlist as the default. The server environment adds `82.156.102.68` and `*.trycloudflare.com` for the public deployment and tunnel.
- Keep the existing same-origin write check. The tunnel forwards the public HTTPS host and scheme to Uvicorn, so the browser origin and app base URL match for writes.

### Server runtime and persistent files

- Install the current working-copy application under `/srv/database/app` and run it as the `ubuntu` user through a dedicated systemd unit.
- Bind Uvicorn to `127.0.0.1:8088`; run a separate `vocabulary-tunnel.service` using the existing `cloudflared` executable to expose it over HTTPS. Do not add an Nginx site or alter the existing HippoArk tunnel.
- Store the SQLite database at `/srv/database/data/vocabulary.sqlite3`. Copy a consistent SQLite backup of the local database before first startup. The app continues writing its operational logs under its server-side application directory.
- Copy the local `.env` to the server with owner-only permissions, then change only its server copy's `DATABASE_PATH` and add generated demo login settings and the public host. Never include `.env` in Git or the deployment commit.
- Do not leave an inbound UFW rule for 8088; public ingress is outbound through Cloudflare. Remove the temporary 8088 rule added during the direct-connect attempt.

### Git and scope

- Commit the design and implementation on `codex/database-public-deploy` and push that branch only if the repository accepts the push. Do not update, force-push, or otherwise modify `master`.
- Exclude `.env`, SQLite files, generated spreadsheets, temporary outputs, logs, and `node_modules` from Git and deployment artifacts.
- Do not stop Vibe-Trading or Neuromesh unless measured memory pressure makes it necessary. Do not stop, reconfigure, or overwrite HippoArk.

## Error handling and recovery

- Validate the production environment file and verify the SQLite backup before starting the systemd service.
- If the app fails to start, read only its dedicated journal/logs, fix the deployment issue, and restart only the new database service.
- If the Quick Tunnel restarts, its generated hostname may change; obtain the current hostname from its dedicated systemd journal.
- Preserve the existing server database on subsequent deployments; never replace it with the local copy after initial deployment.

## Verification

- Check that the app service is active, the public root page loads, and `/api/health` succeeds after authentication.
- Confirm unauthenticated requests receive HTTP 401 and authenticated requests can read the existing vocabulary.
- Confirm the server database path is on server disk and the imported word count remains 79.
- Confirm the final public URL is reachable from outside the server.
- Do not run the project test suite as part of deployment; this request requires a deployment smoke check, not a test-suite run.

## Self-review

- No placeholders remain.
- Authentication is opt-in and therefore does not change local development behavior.
- The production URL, authentication, storage path, runtime, firewall, and Git branch decisions are consistent.
- The plan covers preservation of current local vocabulary data and avoids replacing the GitHub default branch.
