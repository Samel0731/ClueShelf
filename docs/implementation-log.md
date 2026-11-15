# Phase one execution record

## Feature playbook

1. `how` over the affected subsystem.
2. `architect` for parallel design exploration.
3. Write the throughput checkpoint as four todo items.
4. Delegate code-writing to a subagent using your configured feature model.
5. Verify on the matching surface.
6. Rebase into small, ordered commits. skip: no existing Git repository or remote; preserve a reviewable working tree without publishing.
7. If the design is contested, `interrogate` before shipping. Conditional; no contested design yet.
8. Run **Opening a PR**. skip: no repository remote configured, no publishing requested.

## Grounding and data shape

The directory contained the glossary and confirmed MVP spec, with no application code or repository. Phase one has Save and Job entities. Save is owner-scoped and unique by platform content ID. Job belongs to a specific Save version, has a lease token and bounded attempts. API persists Save and Job atomically. A separate worker claims jobs and records content readiness, without pretending AI/extraction is implemented.

## Design candidates

- In-process response background tasks: fewer processes, but pending tasks vanish on server restart and UI/request lifecycle shares ownership with processing.
- SQLite durable jobs and separate worker: one extra process, restart recovery, explicit status, and a stable later AI integration point. Chosen to meet the confirmed durability requirement. A read-only independent reviewer examines transaction and stale-work boundaries.

## Throughput checkpoint

- Blocking first steps: settle API response shape, platform identity and phase-one status meanings before frontend delegation.
- Independent workstreams: frontend owner writes only frontend/; primary owns backend and root scripts/docs; read-only reviewer examines durable work.
- Shared mutable state: application runtime intentionally shares SQLite. Short write transactions serialize claims and completion; platform IDs and content versions protect deduplication and edits. Agents do not share writable source targets.
- Smallest safe decomposition: one frontend owner and one backend owner, with an independent review. No additional application services or queue infrastructure.

## Environment adaptations

User selected small budget and inherit-parent for roles. Cursor Task/poteto-agent types and automatic rule loading are unavailable in Codex; use inherited-model collaboration agents and project-local documentation instead. No global model configuration changed.

## Verification

- `scripts/verify.py` passed: 18 backend cases including migration downgrade/re-upgrade and concurrent duplicates; TypeScript check and production Next.js build passed.
- Real UI on 127.0.0.1:3000: added one explicitly labelled test collection, edited Traditional Chinese/Japanese text, submitted a second URL for the same video and saw the duplicate notice, reloaded and observed persisted content.
- 390px viewport: DOM measurement reported innerWidth 390 and scrollWidth 375, with the responsive layout visible. Temporary viewport override reset afterward.
- Screenshot saved to outputs/phase-one.jpg. The labelled test collection remains in the local development database; no user collection data was imported.
- Independent reviewer identified ORM autoflush before compare-and-swap completion and duplicate flush outside exception handling. Both were corrected before tests. Completion now acquires a short SQLite write transaction before token/version checks.
- Dependency installation and test/build workers needed elevated execution because Windows denied temporary-directory operations. Project-only environments were used; no global packages installed.
- One upstream Starlette warning remains: its TestClient recommends httpx2. Tests pass with the locked httpx dependency; no application failure observed.

## Delivery boundary

Phase one stops at durable collection and author-text readiness. Network extraction and AI are deliberately not connected yet. Status ready is labelled 待 AI 整理 in the UI, not AI completed. Maps, search, lists, backup and authentication remain subsequent milestones.

## Phase two throughput checkpoint

- Blocking first steps: confirm extraction result and analysis contracts before UI integration. Keep original author text distinct from replies and generated fields.
- Independent workstreams: extraction/AI module owner, frontend owner, primary backend integration owner, read-only design and final reviewers. File ownership does not overlap during delegation.
- Shared mutable state: SQLite save/version and lease token are the commit boundary. One pipeline job performs durable read and analyze phases, avoiding multiple same-version job records.
- Smallest safe decomposition: two code owners outside backend integration plus targeted read-only reviews. No additional queue service or MCP layer.

## Phase two changes and checks

- Source/analysis snapshots, manual override flags, separate extraction/AI statuses, title switching and retained duplicate drafts added. Seeded legacy migration tests prove prior manual fields and pending jobs survive. Live database was backed up before upgrading.
- Every slow phase runs outside the write transaction. Heartbeats renew unexpired token-scoped leases. Version and token fencing rejects stale writes. Editing during read cancels that phase's queued/processing indicator to prevent endless UI polling.
- Review fixes: preserve access to duplicate drafts, reject stale AI title selection, mark prior analysis, block browser WebSockets separately from HTTP, and clear old errors on newly queued work.
- Official portable Ollama installed in data/ollama and Qwen3 4B downloaded to data/ollama-models. Logs identified the RTX 3060 CUDA device. This is local inference, with no paid inference API.
- Final scripts/verify.py passed 49 backend tests, TypeScript check and production Next.js build. Upstream Starlette TestClient deprecation warning remains without observed test failure.
- Real source probe: supplied YouTube title/1,666-char description and IG 535-char caption read successfully. Threads share resolved to canonical post with 26-char body; final anonymous response did not include verifiable replies. This is partial success, not a completed popular-comment fetch. The parser supports rooted direct replies when the platform supplies them, excludes nested continuations and unrelated posts.
- Initial real AI run classified all three as Other. Added topic definitions, schema enum and generic multilingual/short-question examples. Final same-source run classified YouTube as 音樂, Instagram as 食譜 and Threads as 餐廳. This is three examples, not a representative quality benchmark.
- Short Threads slang caused unsupported model explanations. For author text under 80 characters with no comments, preserve the original sentence as summary and identify summary_origin=source. AI still supplies title/topics/tags. Longer Japanese content can retain Japanese vocabulary in AI output; broader Traditional Chinese quality evaluation remains pending.
- Final live pipeline report is outputs/phase-two-validation.json. UI confirmed separate source/AI sections, read/analyze buttons, Threads missing-comment fallback and real local results. Screenshot is outputs/phase-two.jpg. Mobile width check: innerWidth 390, content scrollWidth 375; viewport reset after check.
- User-supplied links were saved in the local collection through the UI. No platform credentials or cookies collected, no full videos downloaded. Existing labelled phase-one test content retained.

## Current delivery boundary

## Threads reply fix

User required actual reply capture after the initial partial result. Normal public browser showed replies. Root causes were duplicate preview roots, separate downward-query media using a composite post/user ID, and duplicate case-sensitive HTTP header keys causing a reduced platform response. Fixed root selection, composite ID join and lowercase outbound header merge. Isolated browser forwards only its own anonymous browsing headers/cookies and destroys context after use; cross-host redirects remove cookies/referrer. No user credentials imported.

Live application reread of the original supplied Threads collection persisted 8 top-level replies, ranked likes [203,57,1,1,0,0,0,0]. Independent UI inspection confirmed these replies in the Threads section and a completed local AI summary incorporating them. Screenshot outputs/threads-comments.jpg. This supersedes earlier zero-reply observations for this sample; it remains a bounded public sample, not all replies or a global popularity ranking.

## Phase three: classification and multilingual retrieval

Blocking contract settled before delegation: effective classification and API envelopes. Independent owners implemented search logic, ONNX embeddings and frontend in disjoint files. Primary integrated persistence/API/worker/migrations; an independent reviewer checked privacy, index consistency and races. Shared SQLite writes remain atomic; CPU vectors compute outside transactions with content-fingerprint fencing.

Chosen shape: SQLite SearchChunk rows plus FTS5 and a durable pending-vector scan. No external vector database or additional queue server. This keeps original evidence and embedding ownership together, with explicit pending/failed states. setup_search.py and scripts/verify.py provide rerunnable setup and proof.

Manual topic/tag overrides, keyword/semantic/hybrid modes, facets, snippets and classification reset added. Unchanged vectors retained. Owner isolation, stale summaries, canonical deletion exposing drafts, AI-title transaction consistency and browser polling edge cases reviewed and fixed. Multiple filters use AND. Model-offline requests fall back with notice.

Official pinned E5 ONNX installed locally, CPU inference verified. Final tests 73 passed; typecheck and Next.js production build passed. Live index reached 54 ready chunks with zero pending/failed before UI classification test. Real searches and UI behavior verified as described in search.md. The labelled phase-one test collection was temporarily assigned a test classification, then restored to its original AI/null overrides. Other live classifications were not modified by this verification.

Search UI tested desktop; mobile check recorded separately when performed. Map, list and full backup interfaces remain future work. Broader relevance and model-language evaluation remain pending.

Public source reading, conditional Threads reply sampling and local AI classification are connected. Semantic search, maps, lists, formal login, full backup/restore interface and broader model-quality evaluation remain later milestones. Public platform responses may omit content; source availability is not guaranteed.

## Collection detail visibility fix

Reproduced with 99 filtered cards: detail began 13,212px below the viewport because the responsive workspace placed it after the entire list. Replaced the inline editor with a native modal dialog with independent scrolling, a persistent close header, Escape dismissal, background scroll lock and focus restoration. Desktop has a centered dialog; mobile uses the full viewport. Removed obsolete split-workspace CSS.

TypeScript checking passed. Live browser verification with 1,656 cards showed the dialog top at24px inside a720px viewport; closing preserved scroll position and restored card focus. Mobile390×844 rendered the dialog at0..844 with390px content width. Screenshot: outputs/collection-detail-dialog.jpg. No collection data changed.

## Collection exploration delivery

Custom taxonomy management,30-item paged browse, tag cloud, topic templates and bounded Cytoscape Graph delivered. Details, migration fingerprint and verification evidence are in exploration-implementation.md. Backend113tests/typecheck/productionbuild passed. Live1656collections preserved, backgroundservices resumed.
