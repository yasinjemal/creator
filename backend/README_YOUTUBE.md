This document explains how to wire real Google credentials into the backend for YouTube OAuth testing and E2E flows.

1) Create Docker secret files (recommended):
   - Create two files in `infra/`:
     - `google_client_id` containing your Google OAuth client ID (one line)
     - `google_client_secret` containing your Google OAuth client secret (one line)

2) Update `infra/docker-compose.yml` to declare the secrets and mount them into the `backend`, `worker`, and `token_refresher` services. Example snippet:

secrets:
  google_client_id:
    file: ./google_client_id
  google_client_secret:
    file: ./google_client_secret

services:
  backend:
    # ...
    secrets:
      - google_client_id
      - google_client_secret

3) Alternatively, for local testing you can export environment variables in `.env` at the repo root:
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret

4) Ensure the Google OAuth consent screen and credentials are configured in the Google Cloud Console.
   - The redirect URI you register should match the callback used by the app. For local compose use:
     http://localhost:18000/api/oauth/youtube/callback
   - If running on a remote host, replace `localhost:18000` with the reachable host/port.

5) Restart the compose stack:
   - docker compose down; docker compose up -d --build

6) Test the authorize URL (replace BRAND_ID and REDIRECT_URI):
   - curl "http://localhost:18000/api/oauth/youtube/authorize?brand_id=BRAND_ID&redirect_uri=http://localhost:18000/api/oauth/youtube/callback"
   - The JSON response will contain `authorize_url`. Open it in a browser and complete consent.

7) After Google redirects to your `redirect_uri` with a `code`, call the callback endpoint to exchange for tokens:
   - POST JSON to http://localhost:18000/api/oauth/youtube/callback with {"brand_id": "BRAND_ID", "code": "<code>", "redirect_uri": "http://localhost:18000/api/oauth/youtube/callback"}
   - The response will include the stored token document. The backend will persist the token (encrypted if the encryption key is configured).

8) Verify refresh behavior:
   - Trigger manual refresh:
     POST http://localhost:18000/api/oauth/youtube/refresh with {"brand_id": "BRAND_ID"}
   - The response should contain the refreshed token document if successful.

Admin endpoint protection
- This project supports protecting the admin health endpoint via an API key or basic auth.
- To use API key mode, set `ADMIN_API_KEY` in your `.env` or Docker secret and send header `X-Admin-Key: <key>` with requests.
- To use Basic auth mode, set `ADMIN_USER` and `ADMIN_PASS` and call the endpoint with HTTP Basic auth credentials.

Example curl (API key):

curl -H "X-Admin-Key: your-key" http://localhost:18000/api/admin/oauth/health

Example curl (basic auth):

curl -u adminuser:adminpass http://localhost:18000/api/admin/oauth/health

Rate limiting and admin env vars
- ADMIN_API_KEY: token used when provided in header `X-Admin-Key` for admin requests.
- ADMIN_USER / ADMIN_PASS: HTTP Basic auth credentials alternative.
- ADMIN_RATE_LIMIT: number of requests allowed in window (default 60)
- ADMIN_RATE_WINDOW: window length in seconds (default 60)

If rate limits are exceeded the admin endpoints return HTTP 429.

Notes:
- The backend now prefers Docker secret files at `/run/secrets/google_client_id` and `/run/secrets/google_client_secret` when env vars are not present.
- Keep your client secrets private. For production, use a secrets manager (Vault, AWS Secrets Manager) rather than checked-in files.
- If you run into CORS or redirect issues, double-check that the redirect URI registered in Google Console exactly matches the `redirect_uri` you pass to the authorize endpoint.
