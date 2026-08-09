# Agentic Video Studio

Agentic Video Studio is an evidence-first, autonomous short-form production system for small media and education teams. It turns owned material and live web signals into researched scripts, scene plans, rendered video, QA reports, publication drafts, and measurable strategy updates.

The hackathon path is intentionally end-to-end:

```text
website + brief → Parallel research → evidence-backed idea → Gemini/ADK editorial pipeline
→ Veo scenes → deterministic FFmpeg render → QA and explainable scores
→ approval → YouTube publication draft/upload → metrics → strategy version
```

## Local quick start

Prerequisites: Python 3.12+, Node 22+, pnpm 10+, and FFmpeg.

```bash
cp .env.example .env
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'
pnpm install
.venv/bin/uvicorn apps.api.app.main:app --reload --port 8000
pnpm --filter @avs/web dev
```

Open [http://localhost:3000](http://localhost:3000). The default local token is `demo-token`; mock mode needs no external credentials but still creates a real MP4 with FFmpeg.

Live hackathon deployment: [Agentic Video Studio](https://agentic-video-studio-web-912667618167.us-central1.run.app) · [OpenAPI](https://agentic-video-studio-api-912667618167.us-central1.run.app/docs) · [Grafana](https://agentic-video-studio-grafana-912667618167.us-central1.run.app/d/avs-pipeline)

Live SubSchool proof: [30-second Veo 3.1 + Google TTS + FFmpeg vertical video](https://agentic-video-studio-api-912667618167.us-central1.run.app/media/prj_subschool/gener_0aa01df0fc905674/renders/version_1_9x16.mp4). It was generated through the same live workflow used by the application; it is not a mock fixture.

## Checks

```bash
.venv/bin/ruff check apps/api apps/mcp tests migrations
.venv/bin/pytest
pnpm lint
pnpm typecheck
pnpm build
pnpm test:web
pnpm test:e2e
```

## Provider modes

- `PROVIDER_MODE=mock`: deterministic fixtures and locally rendered media. This is the CI/e2e default.
- `PROVIDER_MODE=hybrid`: real Parallel and Gemini research/editorial calls, local FFmpeg video fallback.
- `PROVIDER_MODE=live`: real Parallel, Gemini, Veo/TTS, and official publisher adapters when their credentials and permissions are available.

Credentials belong in `.env` locally and in the deployment secret store/GitHub Actions secrets remotely. `.env` and generated media are ignored by git. See [configuration.md](docs/operations/configuration.md) and [architecture.md](docs/architecture/architecture.md).

The deployed stack uses Cloud Run, Cloud SQL for PostgreSQL, private Cloud Storage, ClickHouse/Grafana, Artifact Registry, Cloud Build, Secret Manager, Vertex AI (Gemini 2.5 Flash and Veo 3.1), Google Cloud TTS, and Parallel Search. See [deployment.md](docs/operations/deployment.md).

## Repository map

```text
apps/api        FastAPI, state machine, adapters, renderer, application services
apps/mcp        Streamable MCP tools/resources over the same application services
apps/web        Nuxt 4 English product UI
docs            Architecture, contracts, operations, requirement traceability
infra           Deployment and observability templates
tests           Unit, contract, integration, security, and pipeline tests
```

## Safety defaults

Autopublish is off. High-risk claims require human review. TikTok is represented as draft/interactive only. URL ingestion rejects non-public network targets. API keys are stored hashed, webhooks are HMAC-signed, and publication is a prepare/commit operation.

## License

Apache-2.0.
