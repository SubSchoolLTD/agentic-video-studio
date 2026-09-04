## Your business has a story. Now it has a video team.

You built the product. You know your customers. But the content calendar is still empty.

Framewise turns a business website into an always-on short-form video workflow: **research the next worthwhile topic, write and direct the story, generate the video, publish it, and use the response to inform what comes next.** Set the direction once. Let your channel keep moving while you run the business.

[Try Framewise](https://studio.subschool.us) · [Explore the source](https://github.com/SubSchoolLTD/agentic-video-studio)

## Inspiration

For a founder, independent educator, or small media team, regular video production is not one task. It is a chain of jobs: researcher, editor, screenwriter, director, producer, publisher, and analyst. A video model can make a clip, but it does not decide what your audience needs next or manage that entire chain.

We encountered this problem while creating content for SubSchool. The bottleneck was not a missing prompt box. It was the constant human coordination between a promising topic and a finished, published story. Framewise gives a small business the workflow of a short-form production team—without requiring its owner to become one.

## What it does

**Start with your website, not a blank prompt.** Framewise analyzes the product, audience, problem, solution, and relevant search terms. You can correct the resulting brief, choose a balance of educational, entertaining, and product-led content, set a publishing cadence, connect channels, and fund a usage-based balance.

From there, the workflow connects six jobs:

1. **Discover stories worth producing.** Parallel Search finds live web evidence, audience questions, and competing coverage. Candidates retain sources and a rationale, with an opportunity score, audience insight, recommended format, duration, and creative direction.
2. **Build a varied content plan.** Research balances content goals and four video treatments: creator-led UGC, storytelling/sketches, cinematic scenes, and motion graphics. Selected and hidden candidates influence subsequent searches.
3. **Write and direct—not just narrate.** Gemini creates the story structure, character map, exact dialogue, locations, actions, camera direction, and scene prompts. A separate whole-script review checks usefulness, narrative logic, and product accuracy; rejected drafts return for revisions, for up to three review cycles.
4. **Produce the video.** Veo generates scenes with native speech, or the project can use Google Cloud Text-to-Speech. Speaker-specific continuation tracks help carry the right character across scenes. FFmpeg assembles the output with clean cuts; captions are downloadable separately and burning them in is optional.
5. **Keep publishing.** Automation can stop at research, scripts, or finished videos—or continue through publication to connected channels. YouTube uses its official APIs. TikTok and Instagram use encrypted browser sessions and Playwright adapters; availability depends on the platform's sign-in and publishing flow.
6. **Bring the response back to research.** Available publication metrics and editorial decisions become bounded project-specific feedback for the next search. Small samples remain small samples: Framewise does not pretend an early score proves virality.

Want more control? Inspect a source, edit an individual scene, regenerate a script with feedback, or retry a failed stage. Want your own agent to operate the studio? The authenticated REST API and remote MCP interface expose the same project-scoped workflow.

## Why Parallel + Google Cloud

**The most expensive mistake is producing the wrong video.** Parallel is upstream of generation, where better evidence can change what gets made—not a search box added after the fact.

The live backend calls Parallel's Search API directly over HTTPS. It saves request IDs, search queries, URLs, and excerpts, then passes that evidence and the business context into Gemini. The same research process receives selected/hidden themes and available publication-performance patterns, connecting discovery to later editorial decisions.

Google Cloud powers the production side: Gemini handles research synthesis, editorial planning, and review; Veo generates video; Google Cloud Text-to-Speech provides an alternative audio path. Cloud Run hosts the application, Cloud SQL preserves workflow state, Cloud Storage holds media, and Secret Manager protects credentials. Scheduler, Workflows, and Pub/Sub support recurring work and events.

This is a **stateful agentic workflow**, not a claim that a set of chatbots independently runs a studio. Gemini makes structured editorial decisions inside a durable orchestration layer. Tool calls, review/revision loops, budget checks, and saved scene checkpoints turn those decisions into recoverable actions. Runtime model calls use Google's `google-genai` SDK; the code also contains ADK role definitions, but the live orchestration does not depend on an ADK Runner.

## How we built it

The product pairs a Nuxt/Vue interface with a Python/FastAPI backend and typed Pydantic contracts. PostgreSQL stores tenant-scoped projects, candidate decisions, scripts, scene attempts, publishing jobs, and billing records. Rendering uses FFmpeg; ClickHouse and Grafana support operational observability. PayPal handles balance top-ups rather than subscriptions.

The repository includes a credential-free mock-provider path, automated tests, infrastructure configuration, and a runtime evidence map. Test-mode outputs are placeholders, not presented as real Veo results. Public examples on the live site are actual generated videos.

## Challenges and what we learned

**A valid script is not necessarily a good story.** Early drafts could satisfy a schema while saying very little. We moved editorial planning to Gemini 2.5 Pro, expanded the scene contract, and added full-story critique before spending on video.

**Continuity belongs to a character, not the timeline.** Continuing every scene from the immediately preceding clip could transfer a narrator's voice to an on-screen speaker. We introduced character maps and separate continuation tracks. This improves the control strategy; it is not a guarantee of identical voices or perfect lip sync.

**Recovery is part of production quality.** Model limits, rejected outputs, and interrupted work happen. Persisted stages and scene artifacts let the workflow continue from the failed step instead of discarding finished work. Estimates and usage records make the cost visible.

**Feedback needs restraint.** Repeated topics and tiny analytics samples are easy to mistake for learning. The research memory distinguishes editorial preferences from observed performance and preserves room for exploration.

## What we are proud of

Framewise is a working product, not only an architecture diagram: website onboarding, evidence-linked research, detailed scene editing, live generated videos, recoverable production, publishing integrations, balance controls, and agent access are available in one interface.

Our public SubSchool examples demonstrate automatically authored and generated output without manual prompt editing or video editing for those examples. They are examples of production capability—not evidence of customer growth or a guaranteed marketing outcome. The repository includes reproducible tests and code links for the live Google and Parallel calls so the implementation can be inspected rather than taken on trust.

## What's next

The next milestone is evidence of business impact: measure time saved per published video, first-pass production success, cost per usable result, and the number of weeks a channel maintains its chosen cadence. We also want stronger source-to-claim matching, more reliable character/audio consistency, and broader publishing-adapter validation.

**Less coordinating a content pipeline. More seeing your business show up.**
