# Stable character references

Each continuation track belongs to one character or narrator. Every later scene branches from that track's **first accepted take**, not its latest extension. Separate Veo requests are not independent when the previous output is used as their input: voice, appearance and rendering errors can propagate through that chain.

The original accepted clip remains unchanged. A private 24-fps, zero-timestamp reference is trimmed just after its last complete spoken phrase. This keeps speech in the final second, which [Veo's extension guidance](https://ai.google.dev/gemini-api/docs/veo) identifies as necessary for effective voice extension. It is not a persistent voice ID or a guarantee of identical speech.

Reference preparation checks trailing silence in the actual audio signal instead of trusting a model's timing estimate alone. A conservative silence boundary takes priority when available; background music can mask silence, so silence detection is not a substitute for voice recognition. Anchors are versioned so an older cached reference with a silent tail is not reused after a repair.

## Acceptance checks

- Transcript completeness and scene timing.
- Audio-only speaker comparison against the original, using Gemini Pro. Its score is an uncalibrated AI judgment, not a biometric similarity measurement. Uncertainty does not pass.
- Per-scene visual review against the original: recasting, photographic degradation, unstable props and lip synchronization where on-camera speech is intended.
- Failed takes are never promoted to character anchors. Retries use the same original reference.

The cast bible fixes concrete appearance, wardrobe and voice traits. Speech delivery belongs to each scene: on-camera dialogue and intentional voice-over must not receive contradictory instructions. UGC is primarily on-camera creator speech; voice-over is reserved for motivated b-roll.

## Partial regeneration

Replacing a non-root scene replaces only that scene by default. `regenerate_following: true` explicitly includes later scenes of the same track. Replacing a root includes its dependent track. The API freezes the authorized scene IDs and the worker uses that exact set.

Accepted scene files and old rendered versions remain available. New renders receive new version paths, and the final timeline is ordered by storyboard position, including interleaved character tracks. Regeneration usage is settled against its own ledger reference, not charged again against the original production. Additional automatic takes require a balance reservation before calling Veo.

If a batch fails partway through, its accepted scene checkpoints remain reusable. A later regeneration reconstructs the final scene list from those checkpoints rather than restoring stale references from the original completed stage.

## Limitations

Veo video extension conditions on both picture and sound; it is not an independent voice-cloning API. Root anchoring prevents accumulated drift but can constrain location/action changes, and quality review can still make mistakes. Clear, practical scene direction and bounded retries remain necessary. No reference policy can promise perfect speaker identity or artifact-free output.
