# Scaling CreatorFlow

- Use Kubernetes for production: deploy backend as deployments, use Horizontal Pod Autoscaler on CPU/queue metrics.
- Move MongoDB to managed cluster (Atlas) and enable backups.
- Use Redis managed service for caching and locks.
- Use a message queue like RabbitMQ or Redis Streams and workers (Celery/RQ) for media processing and scheduled tasks.
- Serve frontend through CDN and use SSR caching and prerendering for public pages.
- Use feature flags and progressive rollout for new AI features.
