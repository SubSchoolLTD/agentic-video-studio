# Security policy

Please report suspected vulnerabilities privately to **maksim@subschool.us** with the subject `Framewise security report`. Do not post credentials, exploit payloads containing private data, or tenant media in a public issue. Include the affected version, a minimal reproduction, and the expected authorization boundary.

## Deployment boundaries

- Production uses authenticated, tenant/project-scoped resources. Browser sessions, refresh tokens, API keys, and publishing credentials must never be included in screenshots or example configuration.
- Keep local secrets in ignored `.env` files. Use Google Secret Manager for runtime secrets and repository/environment secrets for deployment configuration.
- Prefer keyless Workload Identity Federation over downloadable service-account keys.
- Google OAuth client IDs, cloud project IDs, service names, and public URLs are identifiers—not authentication secrets. Private keys, OAuth client secrets, refresh tokens, and signed media URLs are sensitive.
- Use the narrowest API/MCP scopes. Disconnect publishing channels and revoke integration keys when access is no longer needed.
- Do not enable demo authentication or ship seeded credentials in a public deployment.

## Repository checks

CI runs Gitleaks across the full Git history with redacted output. `.gitleaksignore` contains two documented, narrowly fingerprinted historical non-production findings; do not add broad path exclusions to silence a real leak. Local environment files, databases, Terraform state, browser test artifacts, and private media are ignored.

Making this repository public does not reveal the values of GitHub Actions secrets or Secret Manager secrets. It also does not retroactively remove a secret once committed: if a real credential is ever exposed, revoke/rotate it first and investigate its use. A clean scanner is not a substitute for a security audit or production access review.

## Supported version

Security fixes target the current `main` branch. The deployment is an early-stage product: browser publishing adapters, external platform challenges, provider limits, and generated media all require operational monitoring.
