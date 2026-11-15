# YouTube integration checkpoint

Goal: link one official YouTube channel with read-only OAuth and manually import all liked videos the API exposes. Store metadata only, keep manual edits and imported collections after disconnect.

The implementation has three independent deliverables: OAuth and durable paginated synchronization; source I/O, GPU analysis and CPU indexing lanes; the connection and progress panel. They meet through the existing versioned Save and Job records. A page transaction owns both imported source records and its next cursor. The synchronization worker never waits for AI.

Validation will exercise authorization expiry and replay, repeated sync requests, pagination and interruption, manual preservation, quota and authorization failures, weighted queue selection, migration from existing data, frontend types and build. Real account acceptance additionally requires a configured Google Cloud OAuth client and the owner's consent.

OAuth callback query strings must never be logged. Tokens belong in Windows Credential Manager, not SQLite, frontend state or search text. API-origin source snapshots must bypass the public extractor. No unlike inference or deletion is part of this version.

## Validation result

The full backend suite passed 98 tests. TypeScript checking and the Next.js production build passed. Tests include the official OAuth library's readonly S256 PKCE URL, separate embedded/system browser cookie jars, denied/expired/replayed state, disconnect during authorization and page fetch, paginated imports, unavailable videos, deduplication, source changes, manual preservation, quota pauses, stale leases and weighted AI scheduling. Google responses are simulated; this does not establish real-account acceptance.

Windows Credential Manager passed a real disposable-value write/read/delete check. The probe was removed. The live database was backed up to `data/backups/before-migration-1793545313743548300.db`, then migrated to 0005. Its six existing collections had the same SHA-256 digest over IDs, titles, body text and manual override fields before and after migration.

The running homepage shows the YouTube setup panel, a disabled connect button while unconfigured, and the unchanged six collections. At viewport width 390, document width was 375 with no horizontal overflow. Source IO, AI, YouTube sync and CPU indexing processes are running separately. Screenshot: `outputs/youtube-account.jpg`.

Applied Model the Domain by separating account connection, sync execution and discovered source records. Applied Prove It Works by testing actual credential storage, migration preservation and the live UI in addition to automated checks. Independent reviews found and fixed system-browser cookie isolation, disconnect races, cursor restart exhaustion and transient refresh error handling.

Outstanding acceptance: there is no configured Google Web OAuth client in this environment. Follow `docs/youtube.md`, place the downloaded client at `data/google-client.json`, authorize the owner's account and perform a real sync before marking that acceptance criterion complete. This directory has no Git repository, so no commit or PR was created.
