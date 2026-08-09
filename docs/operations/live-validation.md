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

- API revision: `agentic-video-studio-api-00014-ds8`
- Web revision: `agentic-video-studio-web-00007-vvs`
- Grafana revision: `agentic-video-studio-grafana-00002-2f4`
- API image digest: `sha256:1d6428e6297c346abc13c9bce2d7f768f11f8877a365bf2aed2c808f73b0901c`
- Web image digest: `sha256:c100d4f50a830ebe34cfad373b0f38c88e095688d2d98bd076fb3d6da8d928fe`
- Grafana image digest: `sha256:6c55ad79b9a0741b7de77cf6d5c4b900584f86aa0c4e803299b29dd9fe585910`
- Reproducible ClickHouse image digest: `sha256:28764876c6ea659277563e51c489e5d6afc16acf5e4358eb85c4b5315dfe0e9a`; the live table was migrated in place to preserve its event history.
- Domain event `evt_4eb5e587aa265921` was observed in both ClickHouse and Pub/Sub.
- The scheduled metrics Workflow execution `9be5737f-49cd-4c21-8d6c-2701ccbf0af7` completed successfully.
- Workflow revision `000002-a35` execution `a30bd820-89f7-413c-b251-36b49e05905e` completed all automation and metrics steps. It launched live backlog research `resea_3c6eb1ffd00c69cc`, which completed as Parallel request `search_26696d2fa7fae4d0a7ec00386a4489f3` with four sources and three provenance-linked draft ideas.
- ClickHouse returned the new `correlation_id` column and a `research.completed` event correlated to that run.
- Grafana returned all five provisioned dashboard UIDs: `avs-pipeline`, `avs-ai`, `avs-media`, `avs-publishing`, `avs-cost`.
- The production YouTube provider kill switch was paused and resumed successfully without deleting any jobs.
- `studio.subschool.us` is mapped to the web service and is awaiting its `CNAME studio → ghs.googlehosted.com.` DNS record and managed certificate; the API already allows the custom origin.

## GitHub automation

- Private source repository: [SubSchool/agentic-video-studio](https://github.com/SubSchool/agentic-video-studio).
- The complete CI workflow [run 31309721959](https://github.com/SubSchool/agentic-video-studio/actions/runs/31309721959) passed backend, frontend, mock browser E2E, Terraform, secret scanning, and container build jobs.
- The keyless production deployment [run 31310371308](https://github.com/SubSchool/agentic-video-studio/actions/runs/31310371308) passed from commit `1f23ddbbe5faaeedac19dcf25a913d1e92b280dc` and produced the API and web revisions above.
- GitHub Actions authenticates through a repository-scoped Workload Identity Federation condition; no service-account JSON key is stored in GitHub.
- Runtime Google, YouTube, and Parallel credentials remain in Google Secret Manager. GitHub holds only deployment configuration and Workload Identity identifiers.

## Verification suite

- Backend: Ruff clean and 49 pytest tests passed.
- Mock browser E2E: four Playwright tests passed across desktop and mobile, including create → render → approve → publish.
- Production browser smoke: two Playwright navigation tests passed across desktop and mobile.
- Frontend: ESLint, Nuxt typecheck, Vitest configuration check, and production build passed.
- Infrastructure: Terraform formatting and validation passed.
