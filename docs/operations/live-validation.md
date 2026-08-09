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

The upload remains private intentionally; the rendered proof link above is the judge-accessible artifact.

## Runtime and observability

- API revision: `agentic-video-studio-api-00010-qm9`
- Web revision: `agentic-video-studio-web-00003-wtd`
- Final source commit used for both images: `aa8999c21be869e8b35ce5257c1e9be262427a14`
- API image digest: `sha256:e16065db276cd876357a8af5a25ac67d9e966e7800068bce80f26a53c7c9993f`
- Web image digest: `sha256:a3a8babd15c18e70a387f041d172f9faddae833292afc0a8b9b671a809c14434`
- Domain event `evt_4eb5e587aa265921` was observed in both ClickHouse and Pub/Sub.
- The scheduled metrics Workflow execution `9be5737f-49cd-4c21-8d6c-2701ccbf0af7` completed successfully.

## Verification suite

- Backend: Ruff clean and 27 pytest tests passed.
- Mock browser E2E: four Playwright tests passed across desktop and mobile, including create → render → approve → publish.
- Production browser smoke: two Playwright navigation tests passed across desktop and mobile.
- Frontend: ESLint, Nuxt typecheck, Vitest configuration check, and production build passed.
- Infrastructure: Terraform formatting and validation passed.
