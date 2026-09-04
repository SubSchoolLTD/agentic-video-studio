# Runtime evidence and judging walkthrough

## Start here

- **Live application and public video examples:** https://studio.subschool.us
- **Code:** https://github.com/SubSchoolLTD/agentic-video-studio
- **OpenAPI:** https://agentic-video-studio-api-670288630676.us-central1.run.app/docs
- **Local, credential-free execution:** [README quickstart](../../README.md#run-locally)

Public examples can be watched without signing in. An account is required for a private workspace; real provider generation consumes funded balance. Do not publish a shared administrator password or cloud credential for judging. For zero-provider-cost inspection, run locally in mock mode; its placeholder media is explicitly not a Veo demonstration.

## Follow one story through the product

1. Onboard a website: review the extracted audience, product promise, problem, solution, and keyword groups.
2. Open **Research**: inspect a candidate, its source links, format recommendation, and the research-run history.
3. Open **Productions**: inspect **Characters**, **Script**, a scene's director-prompt modal, and **Storyboard**.
4. Inspect stage outputs and retry history. A completed stage is persisted; the production is not just a browser animation.
5. Watch the final artifact in **Library**. Publication is a separate external operation and follows the project's automation mode and connected-channel state.
6. Open **Strategy** / **Analytics** to distinguish observed metrics from predictions. **Developer** exposes scoped API and MCP access; it does not display stored secrets.

## Required runtime integrations

| Capability | Actual entry point | What to inspect |
| --- | --- | --- |
| Parallel Search | [`ParallelSearchProvider.search`](../../apps/api/app/providers.py) | Direct authenticated `httpx` POST to `/v1/search`; not merely an imported package. Request ID, queries, excerpts, and source URLs are persisted. |
| Google Gemini | [`google_genai_client` and editorial provider](../../apps/api/app/providers.py) | `google.genai` client and actual `models.generate_content` calls; `gemini-2.5-pro` editorial default. |
| Whole-script critique | [`WorkflowService` editorial stage](../../apps/api/app/workflow.py) | `create_package` → `fit_dialogue` → `review_package`; up to three review cycles; feedback returns to generation. |
| Video / speech | [`providers.py`](../../apps/api/app/providers.py) | Live Veo calls, per-speaker continuation, and the Google Cloud TTS alternative. |
| Durable execution | [`workflow.py`](../../apps/api/app/workflow.py), [`repository.py`](../../apps/api/app/repository.py) | Persisted stages, packages, scene attempts, and recovery. |
| Rendering | [`renderer.py`](../../apps/api/app/renderer.py) | Real FFmpeg assembly and media validation in local and deployed modes. |
| Publishing | [`publishing.py`](../../apps/api/app/publishing.py), [`social_browser.py`](../../apps/api/app/social_browser.py) | YouTube API plus separately implemented browser-session adapters. |
| Feedback to search | [`routes.py`](../../apps/api/app/routes.py), [`metrics.py`](../../apps/api/app/metrics.py), [`providers.py`](../../apps/api/app/providers.py) | Selected/hidden patterns and observed publication patterns are passed to subsequent search. |
| External-agent control | [`apps/mcp/server.py`](../../apps/mcp/server.py) | Authenticated Streamable HTTP MCP, forwarding to the same tenant-scoped domain API. |
| Cloud deployment | [`deploy.yml`](../../.github/workflows/deploy.yml), [`infra`](../../infra) | Cloud Run, keyless Google identity, database/media infrastructure, and secret bindings. |

`agents.py` contains Google ADK role definitions, but there is no live ADK Runner orchestration. The working agentic system is the application-managed, durable Gemini/tool workflow. The submission intentionally does not claim an Agent Engine deployment or an independently executing ADK agent network.

## Evidence, not invented metrics

- The [August 9 live-validation record](../operations/live-validation.md) records an actual Parallel request, Veo output, deployment recovery, and a private YouTube upload. It is a dated test record, not a claim that those exact revisions remain current.
- The live site has three public generated examples, also bundled in [`apps/web/public/showcase`](../../apps/web/public/showcase).
- Screenshot assets in this kit come from the live SubSchool workspace. No success states or analytics values were fabricated for the gallery.
- There is no claimed revenue uplift, customer adoption figure, statistically demonstrated learning lift, or guaranteed voice identity.

## Reproducible verification

```bash
.venv/bin/ruff check apps/api apps/mcp tests migrations
.venv/bin/pytest
pnpm --filter @avs/web lint
pnpm --filter @avs/web typecheck
pnpm --filter @avs/web test
pnpm --filter @avs/web build
pnpm --filter @avs/web test:e2e
```

Backend verification during final packaging: **135 tests passed**. A Pydantic-settings forward-reference warning remains; the test run completed successfully. CI additionally runs frontend checks, browser E2E, Terraform validation, full-history secret scanning, and container builds.

## Contest references

The [official rules](https://agentic-cinema.devpost.com/rules) specify an English submission, public licensed source, a hosted application, and a public demo of at most three minutes. The four judging dimensions are equally weighted. The [Parallel track page](https://agentic-cinema.devpost.com/details/parallel-resources) requires actual runtime Search API use; the direct HTTPS integration above supplies it.

The product runtime uses Google AI services and Parallel, without a non-Google model provider or external AI agent framework. Development assistance is separate from runtime architecture; any organizer question about development tools should be answered transparently.
