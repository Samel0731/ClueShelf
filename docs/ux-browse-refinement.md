# Browse refinement

Considered two layouts before implementation:

1. Sidebar filters plus separate settings page. More navigation and less room for graph on laptops.
2. Inline scope summary plus account dialog. Keeps search, chips and result counts together; account setup leaves the browsing path. Selected this layout using the existing dialog pattern.

Display choices are cards, compact list and graph. Topic adaptation is a card option rather than a second indistinguishable display. Lists use one-line titles and excerpts. Tag lookup searches the full current facet list, with counts and an explicit AND explanation.

Filter changes retain previous content with a disabled, dimmed pending state until atomic replacement. A bounded, 60-second in-memory cache allows quick return to recent scopes; explicit refresh bypasses it. Search debounce applies to text entry only. Existing generation fences discard stale requests.

Graph wheel sensitivity increases from 0.15 to 0.8. Branch headings report loaded / total counts and provide explicit load-more and collapse actions.

Validation: 15 focused browse/catalog tests passed, TypeScript and production build passed. Live API browse took 0.34–0.50 s after the change versus 3.0–3.3 s before; graph overview took 0.166 s. Batch catalog lookup uses two queries, covered by a regression test. Browser verified 30 initial items, account dialog, filter pending state, graph branch 30/483, retained branch after switching displays, and mobile width without horizontal overflow.

## Second pass: reduce the distance to collections

Compared keeping the full word cloud open with a preview of the 12 most used tags and an explicit expand action. Selected the preview so results remain closer to the search controls; tag lookup still searches all scoped tags and can show up to 60 matches. Reduced the hero and capture spacing rather than moving capture into another screen. Search index maintenance is disclosed on request. Added a slash shortcut outside editable fields/dialogs, explicit all-topics reset, full selected tag names in scope, and a partial reset for empty results. Pending results and facets are inert so keyboard users cannot act on an outdated scope.

Second-pass validation: production build and TypeScript passed. Live browser verified 12-to-60 tag expansion, slash shortcut focusing shelf-search, Threads + music empty result, partial reset preserving Threads and restoring two results, and a 390px mobile viewport without horizontal overflow. Capture uses native details for progressive disclosure. No backend or stored collection changes.
