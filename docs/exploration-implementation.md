# Collection exploration implementation checkpoint

Goal: manage a growing collection with custom classifications, 30-item pages, a tag cloud, topic templates and an expandable co-occurrence graph. Preserve manual edits and existing collection content.

The taxonomy catalog owns canonical names, aliases, merges and archive rules. Cached SaveTaxon associations let paging, cloud and graph queries share effective classifications. Browse owns stable query contexts and ten-minute search snapshots. The frontend owns view preference, loaded pages and independent detail dialogs. Cytoscape renders only a bounded overview and explicitly expanded collections.

Alternative considered: continue deriving effective arrays on every browser refresh. Rejected because loading all full Save bodies would retain the current large-collection cost and make merges inconsistent across views. The selected catalog plus indexed membership approach keeps raw AI snapshots unchanged while providing a single canonical interpretation.

Throughput checkpoint: taxonomy/AI integration, browse/graph aggregation and shelf UI run in disjoint files after agreeing API contracts. Root owns integration, the graph renderer and live verification. Network calls and local inference remain outside short database write transactions. One GPU worker runs classification and requested organization suggestions.

Acceptance includes migration preservation, alias and archive behavior during background jobs, stable pagination and search snapshots, full-context counts, graph expand/collapse/deduplication/limits and desktop/mobile UI. Existing live collection before migration:1656 records, SHA256 over IDs, titles, bodies, manual overrides, source and analysis snapshots a2d12a2daf5d1accfe6c5392f01b69948bbf57960edd1c0aea271a6d0f37e3d4.

## Delivered and verified

Full verification passed113 backend tests, TypeScript checks and the Next.js production build. Targeted tests cover aliases/merge/archive, dynamic AI topics, stale AI writes, manual classification during queued work, search/paging snapshots and Graph scope/count/limit behavior.

Live database backed up to data/backups/before-migration-1793697726650394400.db and migrated from0005 to0007. All1656 collection records retained the exact pre-migration fingerprint above, including source, analysis and manual overrides. Membership cache contains8998 associations.

Live browser verified first30 items and load-more60; music uses the music list template; full-result tag cloud shows the top60 tags. Graph overview shows9topics/40tags, a program branch expands30 of483 collections, detail opens and closes correctly, and switching cards/Graph preserves expanded branches. Refreshing Graph also refreshes the parent result scope to keep cloud and Graph aligned. A rename preview reported172 affected music collections and was canceled without mutation.

A real requested local AI organization job completed with one proposal and zero applied changes. Suggestions use bounded recent samples, not an exhaustive scan; approval remains explicit. Keywordsearch found Threads reply evidence for棠記; semanticsearch for冷凍備餐料理 returned Japanese recipe content. Mobile390px viewport had375px document width and303px graph stage width without overflow. Final Graph image saved in the Codex outputs directory.

Model the Domain kept taxonomy identity and effective memberships separate from immutable raw snapshots. Prove It Works required data-fingerprint comparison, real local inference and browser interaction in addition to tests. No Git repository exists in this checkout, so no commit or PR was created.
