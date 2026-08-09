# P0 requirement traceability

This matrix is the working acceptance map. `mock` means deterministic provider fixtures exercising our contracts; `live` means the same adapter is invoked against the provider.

| Capability | Implementation | Acceptance |
|---|---|---|
| Organization/project isolation | Principal scope + tenant-aware resource repository | Cross-tenant API tests return 404 |
| Website/brief/brand profile | Project wizard and versioned profile resource | Editable detected profile, activation gates |
| Manual, URL, text, RSS, REST intake | Source endpoints + safe fetch + feed parser | Idempotent source item creation |
| Parallel runtime research | `ParallelSearchProvider` | Request ID, objectives, sources, excerpts persisted |
| Ideas and opportunity score | Evidence packet + weighted scorer | Breakdown and confidence shown |
| Script/fact-check/storyboard | Google ADK/Gemini structured stages + mock equivalent | Unsupported/high-risk claims block media |
| 9:16 and 16:9 output | Veo adapter or motion fallback + FFmpeg renderer | Valid H.264/AAC files and checksums |
| Selective regeneration | Scene attempt resource and locked-scene guard | Only selected scene attempt increments |
| QA/readiness/performance/confidence | Independent technical/content/brand/platform reports | Hard gates separate from scores |
| Approval and autopilot policy | Approval transitions + system minimum thresholds | High risk never autopublishes |
| Publishing | YouTube OAuth/upload; TikTok capability/export fallback | prepare/commit and provider states |
| 24h/7d metrics and learning | Idempotent YouTube Data/Analytics collector + metric checkpoints + performance review + versioned strategy | Missing metrics remain missing, not zero |
| REST/API keys/webhooks | OpenAPI, hashed scoped keys, HMAC deliveries | Contract, replay, scope, idempotency tests |
| MCP | Project/source/research/generation/approval/publication tools | Dry-run and prepare/commit tests |
| Observability | Live ClickHouse event/metric sink + provisioned Grafana dashboard | Correlated real events and datasource health check |
