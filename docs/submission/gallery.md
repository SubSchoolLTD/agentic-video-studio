# Framewise gallery

Six 3:2 images for Devpost and the public README. Each PNG is 1050 × 700 and below the 5 MB Devpost limit. Use image 01 as the project thumbnail.

1. [Your business. Your stories. On autopilot.](../media/01-always-on-studio.png)
2. [Find the next story worth telling.](../media/02-research.png)
3. [More than a voiceover. A real scene.](../media/03-director.png)
4. [Set a cadence. Get your time back.](../media/04-automation.png)
5. [The story. The footage. The finished cut.](../media/05-production.png)
6. [Your agent. Your studio. One workflow.](../media/06-agent-access.png)

## Provenance

The product panels are actual screenshots of the live Framewise interface, captured on September 5, 2026. The cover uses stills from the real generated videos already published in the Framewise showcase, not invented product screenshots or stock portraits. No metrics, controls, successful states, or generated scenes were fabricated for this gallery.

Account header chrome was cropped out. The screenshots are framed with code-native typography, backgrounds, and a simple clapperboard mark. The automation screenshot shows the workspace's actual research-only setting, not a claim that this workspace had all-channel publishing enabled.

Showcase originals: [media directory](../../apps/web/public/showcase). These are AI-generated scenes created for this project; they do not depict customer testimonials or claim endorsement by the people represented. Google and third-party product names refer to their respective services.

## Rebuilding

[`scripts/build_submission_gallery.mjs`](../../scripts/build_submission_gallery.mjs) produces editable HTML layouts from local live captures in `output/playwright/launch`. Raw account screenshots are intentionally not committed. Supply `research.png`, `director.png`, `automation.png`, `production.png`, and `developer.png`, with the same screen framing, then run:

```bash
node scripts/build_submission_gallery.mjs
```

The 1500 × 1000 design is displayed at 70% for a normal browser capture. Capture the page, crop the top-left 1050 × 700 canvas, and inspect every exported image before use. Avoid the in-app browser's stitched full-page export for this layout: its current device-scale behavior can duplicate or shrink content.
