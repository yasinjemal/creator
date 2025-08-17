# CreatorFlow API

## Brand endpoints
- POST /api/brand -> create brand profile
- GET /api/brand/:id -> get brand

## Content endpoints (planned)
- POST /api/content/generate -> generate content for a brand + platform
- POST /api/content/schedule -> schedule content for posting
- GET /api/content/:id -> get content

## Auth
- OAuth connectors per platform (implement per-platform adapters)

Notes: Use JWT for user sessions; keep platform tokens encrypted in DB.
