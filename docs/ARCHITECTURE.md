# CreatorFlow Architecture

Overview of components and responsibilities:

- Frontend (Nuxt 3): user interface for brand and content creation, preview, calendar, analytics.
- Backend (Flask): API endpoints for brand management, content generation, scheduling, analytics ingestion.
- Database: MongoDB for storing brands, content drafts, campaigns, schedules.
- Cache: Redis for short-term caching and rate-limiting.
- Media: FFmpeg and Pillow used in worker containers for video/image processing.
- AI: GPT-5 API used for content generation; backend will include AI client wrapper and prompt templates.
- Integrations: OAuth connectors for social platforms. Each platform will have an adapter implementing upload and analytics ingestion.
- Orchestration: docker-compose for local dev; production should use Kubernetes/Helm and managed MongoDB/Redis.

Scaling notes:
- Use async workers (Celery/RQ) for media processing and scheduled posts.
- Shard MongoDB or use managed clusters for high volume.
- Use autoscaling for worker pools based on queue size.
