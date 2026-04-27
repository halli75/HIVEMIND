# Lessons

- For heavy project tasks, keep the main thread in a project-manager role: delegate disjoint engineering slices to subagents, then integrate and verify centrally.
- Do not stop a live integration at a broad "not demo-stable" conclusion when the user expects an end-to-end proof; isolate the failing layer, run a patch matrix in parallel, and return either proof or the exact remaining upstream/environment blocker.
- When a live integration fails because a third-party network endpoint is unreachable, do not treat classification as completion. Continue with current-doc research, alternate official/community endpoints, cloud-region tests, and a prepared/submitted escalation path until there is either a live proof or a concrete external wait state.
