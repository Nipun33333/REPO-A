# Optional content optimization

This upgrade keeps REPO-A's broad US trend discovery, canonical subject, Gemini
router, Edge TTS, footage validation, FFmpeg/MoviePy renderer, resumable uploader,
OAuth preflight and production schedule. It introduces no paid service or new
OAuth scope. The scheduled workflow is unchanged and optimization is **off by
default**. Scores are heuristic diagnostics, never promises of views or retention.

## Configuration

| Variable | Default | Behavior |
|---|---|---|
| `YT_OPTIMIZATION_ENABLED` | `0` | `1`, `true`, or `yes` enables content improvements and the report |
| `YT_OPTIMIZATION_TIMEOUT_SECONDS` | `20` | Per-request timeout; clamped to 1–60 seconds; invalid values use 20 |
| `YT_TREND_DIAGNOSTICS_ENABLED` | `0` | Independent, read-only diagnostics from existing discovery data |
| `YT_TREND_HISTORY_PATH` | empty | Optional local historical JSON for channel-relative metrics |

Add settings to the existing local environment when ready. Do not replace your
`.env` or OAuth files. Setting `YT_OPTIMIZATION_ENABLED=0` restores the legacy
script/metadata path with zero optional Gemini calls and no quality report write.
Thumbnail failure isolation and Linux font support are reliability fixes that
also apply when optimization is disabled.

## Architecture and acceptance rules

1. The existing scriptwriter receives extra retention guidance only when enabled:
   immediate subject confirmation, clear transitions, concise narration, explicit
   payoff and one short CTA. Existing JSON fields and formats stay the same.
2. After existing script validation, one optional Gemini request proposes five
   hooks, five titles, thumbnail text, description, tags and search targets.
3. Deterministic checks reject off-topic text, newly introduced numeric literals,
   malformed responses and unsafe metadata characters. A second independent
   Gemini request checks semantic support and whether the body fulfills promises.
   Missing, invalid or failed review rejects all proposals.
4. Hooks use specificity, curiosity, brevity, relevance and engagement scores:
   60% of their mean plus 40% of their minimum. Only a strictly better approved
   hook replaces the first spoken sentence. The rest of the opening remains.
   Titles must also improve on the original score. Mobile/desktop length warnings
   are heuristics, not exact layout predictions. Numbers receive no score bonus.
5. Each change is transactional. The existing topic/query validator runs along
   with identity and section-field equality checks. Narration changes must remain
   within 70–85 words for three-section Shorts or 920–1100 for nine-section long
   videos. Four subject-specific video queries and renderer fields are preserved.
   An original script outside the target is reported; it is not silently rewritten.
6. SEO accepts only reviewed description and metadata. It deduplicates and bounds
   tags, keywords and three search targets; hashtags have one prefix, at most three
   entries and one `#Shorts` for Shorts. Only marked optimized scripts use the new
   upload description builder, leaving legacy payload construction intact.
7. Thumbnail text must be 1–3 words copied from the narration, reviewed for context
   and complementary to the final title. Existing local media, contrast, wrapping
   and image-size handling are reused. Optimized long thumbnails use 1280×720;
   Shorts retain 1080×1920. Corrupt media falls back to a plain background; total
   thumbnail failure does not fail the video upload. Shorts display/application
   remains subject to YouTube behavior and is not guaranteed.
8. Pacing edits only remove adjacent repeated complete sentences, subject to the
   same word-budget and topic checks. Broad body rewrites are intentionally absent.

There are at most two application-level optional Gemini attempts, each using the
existing active model/client with an HTTP timeout and a 3072-token output limit, no model failover loop, no
whole-task recovery or application retries. Existing research/script/render calls
keep their existing recovery behavior. Network/SDK overhead may add elapsed time;
this is not a process-level hard deadline. Provider exception bodies are not logged
by the optional path.

The semantic review reduces hallucination risk; it cannot establish real-world
truth. It is grounded in existing narration, not independent external research.
Claims already incorrect in the original script remain an upstream limitation.

## Reports

Enabled runs write `output/content_quality_report.json` before media generation:
canonical topic and video type, candidate scores and approvals, original/final
hook and title, thumbnail text, SEO/description/tag checks, query coverage, word
count, estimated narration time at 150 words/minute, validation status, enabled
features, warnings and fallbacks. This estimate does not change existing render
or TTS duration targets. Actual audio length depends on voice and pacing.

Reports use selected diagnostic fields, redact known environment secrets and
common credential patterns, and never include provider exceptions or raw config.
Discovery and semantic-selection errors now log only an allowlisted error type
and numeric HTTP status when available. Provider messages, request URLs, headers
and response bodies are omitted, including chained exceptions at service boundaries.
Source/topic log labels redact configured credentials and omit URLs; returned
content and ranking are unchanged.
Report I/O failure is non-blocking. Reports are per-run output and existing cleanup
removes them on the next run. Root `used_topics.txt` and `used_media.json` persist.

## Optional trend diagnostics

When enabled, existing discovery requests include `contentDetails` as an additional
part (no extra requests). `output/trend_diagnostics.json` contains observed age,
views/hour and engagement when sufficient fields exist. No diagnostic changes
ranking, canonical selection or duplicate protection.

Do **not** use the popularity-filtered discovery pool as a historical median.
Provide a JSON list of independently collected historical observations if available:

```json
[
  {"video_id":"historical-id", "channel_id":"stable-channel-id",
   "video_type":"under_3m", "age_hours":24, "views":1234}
]
```

The example is a schema illustration, not measured data. A metric requires four
unique historical videos from the candidate's channel, excluding the candidate,
with the same duration band and observed age within 25% of its current age.
Bands: `under_3m` (≤180s), `3m_to_15m` (≤900s), `over_15m`. These are duration bands,
not a claim that a video is a YouTube Short. Zero medians and incomplete records
are skipped. A ≥2× median result is a diagnostic outlier, with a simple question/
statement title pattern. No causal claim or view prediction is made. The optional
history file is read only; no private analytics API is accessed.

## Offline audience retention

Normalize a user-provided CSV to exactly `position,retention` columns. Units must
be explicit; the tool never mistakes a short video's seconds for percentages.

```powershell
python -m agents.content_optimization.retention retention.csv
python -m agents.content_optimization.retention retention.csv --axis percent --duration 600
python -m agents.content_optimization.retention retention.csv --retention-unit fraction
```

Default retention values are percentages. Fraction inputs use values such as 0.8.
The CLI reports opening retention (interpolated at 30 seconds, or the last sample
for shorter videos), drops of at least five percentage points ranked by slope,
middle loss rate and an improvement suggestion. Above-100% rewatching is allowed.
Malformed, missing/empty, non-finite, negative and non-increasing samples are
rejected with row-numbered validation errors. Blank rows, extra cells and broken
quoting are rejected rather than silently skipped. LF, CRLF and UTF-8 BOM files
are supported. The CLI exits with code 2 and no traceback for expected input/file
errors; percent signs are accepted only for columns using percent units. Causes
cannot be inferred from the graph alone. Export headers vary, so normalization
is required. This standalone standard-library utility makes no network calls,
does not load OAuth and does not participate in production uploads.

## Verification and safe rollout

Offline tests (all external generation, upload and media operations mocked):

```powershell
python -m pytest -q
python -m compileall -q agents tests pipeline.py uploader
git diff --check
```

After explicit authorization for live external requests, an upload-disabled test:

```powershell
$env:YT_OPTIMIZATION_ENABLED="1"
$env:SKIP_YOUTUBE_UPLOAD="1"
$env:PIPELINE_VIDEO_TYPE="shorts"
python -m pipeline
```

Use `long` for a second test. Bash equivalent:

```bash
YT_OPTIMIZATION_ENABLED=1 SKIP_YOUTUBE_UPLOAD=1 PIPELINE_VIDEO_TYPE=shorts python -m pipeline
```

**This is not offline:** it calls Gemini, discovery, footage and TTS services.
The pipeline clears its output directory and still records completed topics/media
in production history even when upload is skipped. Prefer an isolated REPO-A copy
with disposable output/history for this validation; leave production history intact.
Do not run OAuth preflight for an upload-disabled local test. No live run was
performed as part of this implementation.

Inspect final script, report, narration, render and thumbnail for both formats.
Keep optimization disabled until that review is satisfactory. A later deployment
can explicitly add `YT_OPTIMIZATION_ENABLED=1` to the pipeline step environment;
this upgrade does not change that production workflow or enable it automatically.
Rollback is the flag set to `0`. No push, merge, upload, credential rotation or
schedule change is needed for local testing.

Deferred: automated comment replies, calendar changes, channel audits, private
Analytics scopes, generated imagery, timestamp chapters, broad narration rewrites
and prediction models. The eleven reference skills were reviewed; only techniques
useful to the current automated pipeline were integrated. See
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) for attribution and license.
