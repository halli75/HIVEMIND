# Lessons

- For heavy project tasks, keep the main thread in a project-manager role: delegate disjoint engineering slices to subagents, then integrate and verify centrally.
- Do not stop a live integration at a broad "not demo-stable" conclusion when the user expects an end-to-end proof; isolate the failing layer, run a patch matrix in parallel, and return either proof or the exact remaining upstream/environment blocker.
