# Live validation record

Validated against the production deployment on 2026-08-09.

## Provider workflow

- Project: `prj_subschool`
- Generation: `gener_0aa01df0fc905674`
- Video: `video_57dafbdb5c6eb560`
- Parallel Search request: `search_6d35dfa17615bb38fefd661bd9cfb6dc` with six cited sources
- Editorial planning: Vertex AI Gemini with strict structured output
- Scene generation: five real Veo 3.1 scenes
- Narration: Google Cloud Text-to-Speech
- Assembly: FFmpeg, captions, H.264/AAC, 720×1280, 30 fps, 30 seconds
- Automated QA: pass; publish readiness 89; predicted performance 82 at 0.74 confidence
- SHA-256: `b33ed72e0c5182df1a5fa4ec7bef511a26d73be20f2602e4ab12f18ed7a6bc23`
- [Rendered proof video](https://agentic-video-studio-api-912667618167.us-central1.run.app/media/prj_subschool/gener_0aa01df0fc905674/renders/version_1_9x16.mp4)

## YouTube integration

- OAuth refresh-token retrieval and channel resolution were verified against the official YouTube Data API.
- The resolved brand channel is `SubSchool` (`UCDNBUTZ_hWH_yqcSGq4AwDQ`).
- The generated video was uploaded with the resumable YouTube API as `private`, explicitly marked as synthetic media and not made for kids.
- Private integration-test video ID: `0RtokaoQf9U`.
- A fresh official status read returned `processed`, `private`, duration `PT31S`.
- The official Data/Analytics collector returned API versions `v3`/`v2`, real zero public counters, and marked unavailable private-video analytics as unavailable rather than inventing values.

The upload remains private intentionally; the rendered proof link above is the judge-accessible artifact.

## Runtime and observability

- API revision: `agentic-video-studio-api-00012-gbz`
- Web revision: `agentic-video-studio-web-00006-b96`
- Grafana revision: `agentic-video-studio-grafana-00002-2f4`
- API image digest: `sha256:d20c634d4ae8ceb166402afa2244da7b794144a1e6b7cc71a4208266f7b0b74e`
- Web image digest: `sha256:726fd0059f1e39cdad4f0b0e7a205366df92c7421f876665b1850ca05a6b2c9e`
- Grafana image digest: `sha256:6c55ad79b9a0741b7de77cf6d5c4b900584f86aa0c4e803299b29dd9fe585910`
- Reproducible ClickHouse image digest: `sha256:28764876c6ea659277563e51c489e5d6afc16acf5e4358eb85c4b5315dfe0e9a`; the live table was migrated in place to preserve its event history.
- Domain event `evt_4eb5e587aa265921` was observed in both ClickHouse and Pub/Sub.
- The scheduled metrics Workflow execution `9be5737f-49cd-4c21-8d6c-2701ccbf0af7` completed successfully.
- Workflow revision `000002-a35` execution `a30bd820-89f7-413c-b251-36b49e05905e` completed all automation and metrics steps. It launched live backlog research `resea_3c6eb1ffd00c69cc`, which completed as Parallel request `search_26696d2fa7fae4d0a7ec00386a4489f3` with four sources and three provenance-linked draft ideas.
- ClickHouse returned the new `correlation_id` column and a `research.completed` event correlated to that run.
- Grafana returned all five provisioned dashboard UIDs: `avs-pipeline`, `avs-ai`, `avs-media`, `avs-publishing`, `avs-cost`.
- The production YouTube provider kill switch was paused and resumed successfully without deleting any jobs.

## Verification suite

- Backend: Ruff clean and 49 pytest tests passed.
- Mock browser E2E: four Playwright tests passed across desktop and mobile, including create → render → approve → publish.
- Production browser smoke: two Playwright navigation tests passed across desktop and mobile.
- Frontend: ESLint, Nuxt typecheck, Vitest configuration check, and production build passed.
- Infrastructure: Terraform formatting and validation passed.
