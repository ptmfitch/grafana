---
name: sync-grafana-upstream
description: Syncs this Grafana fork with the latest grafana/grafana main branch, rebuilds the local checkout, starts and verifies the development servers, and always stops them afterward. Use when asked to update, refresh, or test the fork against upstream Grafana.
disable-model-invocation: true
---

# Sync Grafana upstream

Run the checked-in workflow from the repository root:

```bash
python3 .cursor/skills/sync-grafana-upstream/scripts/sync_and_verify.py
```

The workflow:

1. Requires a clean `main` branch so local work is not overwritten.
2. Adds the `upstream` remote for `grafana/grafana` if it is missing.
3. Fetches and merges `upstream/main` with a merge commit when required.
4. Installs immutable frontend dependencies and builds the backend and frontend.
5. Starts `make run` and `yarn start`, then verifies `/api/health` and `/login`.
6. Stops both process groups on success, failure, or interruption.

Do not push the result. Grafana's human review gate requires explicit approval before any
`git push`.

If the merge conflicts, stop and report the conflicted files. Do not resolve conflicts or abort
the merge unless the user asks. If a build or health check fails, report the command and the log
directory printed by the script. Confirm that the final output says both servers were stopped.
