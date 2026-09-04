# Live validation record

Validated against the production deployment on 2026-08-09. This is a historical validation record; revisions, prices, and test totals below describe that date, not the current release. See the [current submission evidence map](../submission/runtime-evidence.md).

## Provider workflow after account migration

- Project: `prj_subschool`
- Google Cloud project: `upheld-dragon-505012-v3` (`670288630676`)
- Generation: `gener_0c7a514e2be252e3`
- Video: `video_93e1949ce5975a47`
- Parallel Search request: `search_0b107dfb8325b1d59cbd1dbe8d4ef9b6`
- Editorial planning: Vertex AI Gemini with strict structured output
- Scene generation: five real Veo 3.1 scenes
- Narration: Google Cloud Text-to-Speech
- Assembly: FFmpeg, captions, H.264/AAC, 720×1280 and 1280×720, 30 fps, 30 seconds
- Technical QA: both ratios passed; publish readiness 89; predicted performance 82 at 0.53 confidence
- Manual review: completed and approved; no public publication was triggered
- SHA-256 (9:16): `381696e2ccfa0e94f783bbe5be2e7c3f617efe9bbff951927d6a7d1e64a063d8`
- Rendered proof video is retained in private Cloud Storage and is exposed only through an expiring URL returned to an authorized SubSchool workspace member.

The live job crossed a rolling API deployment while generating scenes. Revision `agentic-video-studio-api-00003-bwc` resumed from the persisted storyboard/scene checkpoint and finished without duplicate provider work, validating the durable recovery path in production.

## YouTube integration

- OAuth refresh-token retrieval and channel resolution were verified against the official YouTube Data API.
- The resolved brand channel is `SubSchool` (`UCDNBUTZ_hWH_yqcSGq4AwDQ`).
- The generated video was uploaded with the resumable YouTube API as `private`, explicitly marked as synthetic media and not made for kids.
- Private integration-test video ID: `0RtokaoQf9U`.
- A fresh official status read returned `processed`, `private`, duration `PT31S`.
- The official Data/Analytics collector returned API versions `v3`/`v2`, real zero public counters, and marked unavailable private-video analytics as unavailable rather than inventing values.

The upload remains private intentionally; the rendered proof link above is the judge-accessible artifact.

## Runtime and observability

- API revision: `agentic-video-studio-api-00003-bwc`
- Web revision: `agentic-video-studio-web-00003-ls9`
- Grafana revision: `agentic-video-studio-grafana-00001-l9x`
- Runtime images are addressed by immutable commit tags in Artifact Registry; the database and media history were migrated in place.
- Domain event `evt_4eb5e587aa265921` was observed in both ClickHouse and Pub/Sub.
- The scheduled metrics Workflow execution `9be5737f-49cd-4c21-8d6c-2701ccbf0af7` completed successfully.
- Workflow revision `000002-a35` execution `a30bd820-89f7-413c-b251-36b49e05905e` completed all automation and metrics steps. It launched live backlog research `resea_3c6eb1ffd00c69cc`, which completed as Parallel request `search_26696d2fa7fae4d0a7ec00386a4489f3` with four sources and three provenance-linked draft ideas.
- ClickHouse returned the new `correlation_id` column and a `research.completed` event correlated to that run.
- Grafana returned all five provisioned dashboard UIDs: `avs-pipeline`, `avs-ai`, `avs-media`, `avs-publishing`, `avs-cost`.
- The production YouTube provider kill switch was paused and resumed successfully without deleting any jobs.
- `studio.subschool.us` is mapped to the web service in `upheld-dragon-505012-v3`; the existing `CNAME studio → ghs.googlehosted.com.` is retained and Google manages the certificate. The API allows the custom origin.

## GitHub automation

- Source repository (now public): [SubSchoolLTD/agentic-video-studio](https://github.com/SubSchoolLTD/agentic-video-studio).
- The complete CI workflow [run 31316853362](https://github.com/SubSchoolLTD/agentic-video-studio/actions/runs/31316853362) passed backend, frontend, mock browser E2E, Terraform, secret scanning, and container build jobs.
- The account migration [run 31316128598](https://github.com/SubSchoolLTD/agentic-video-studio/actions/runs/31316128598) copied durable data and media into the new project without storing a service-account key.
- The final keyless production deployment [run 31316858226](https://github.com/SubSchoolLTD/agentic-video-studio/actions/runs/31316858226) passed from commit `b32525f` and produced the API and web revisions above.
- GitHub Actions authenticates through a repository-scoped Workload Identity Federation condition; no service-account JSON key is stored in GitHub.
- Runtime Google, YouTube, and Parallel credentials remain in Google Secret Manager. GitHub holds only deployment configuration and Workload Identity identifiers.

## Verification suite

- Backend: Ruff clean and 50 pytest tests passed.
- Mock browser E2E: four Playwright tests passed across desktop and mobile, including create → render → approve → publish.
- Production browser smoke: two Playwright navigation tests passed across desktop and mobile.
- Frontend: ESLint, Nuxt typecheck, Vitest configuration check, and production build passed.
- Infrastructure: Terraform formatting and validation passed.
