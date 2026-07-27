---
name: grafana-dev
description: Start, stop, restart, or reload-frontend for local Grafana (make run + yarn start). Use when the user asks to start, stop, restart, kill, shut down, bring up, or bounce Grafana locally, or after making visual/UI frontend changes that should appear for admin/admin.
---

# Grafana local servers

From the repository root, run:

```bash
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py <command>
```

## Intent mapping

| User says | Command |
|-----------|---------|
| stop, kill, shut down, halt, bring down (or equivalent) | `stop` |
| start, run, up, restart, bounce, or any other request to have Grafana running | `start` |
| reload frontend, refresh UI, visual-only change, frontend-only bounce | `reload-frontend` |

`start` is smart: **if servers are running, restart them; if not, start them.**

`reload-frontend` restarts only webpack (`yarn start`) and leaves the backend running. Prefer this after visual/UI-only changes.

Also available: `status`, `restart` (always stop then start both).

## After visual / UI changes

**Do this automatically — do not wait for the user to ask.**

After editing frontend visual/UI code (components, styles, homepage, dashboards, layout), run:

```bash
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py reload-frontend
```

If the backend is not running, use `start` instead. Use full `restart` / `start` when Go/backend or shared config also changed.

## Rules

1. Always run the script from the Grafana repository root.
2. Prefer the script over ad-hoc `make run` / `yarn start` / `kill` so both backend and frontend stay in sync.
3. After `start`, `restart`, or `reload-frontend`, report the printed status (URLs, log paths). Do not leave servers unmanaged in a separate terminal unless the script fails.
4. Default login after a healthy start: `admin` / `admin` at http://127.0.0.1:3000
5. Demo UI must be visible for that default admin login on the standard home page and dashboards (see `.cursor/rules/demo-ui-visibility.mdc`).

## Commands

```bash
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py status
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py start
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py stop
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py restart
python3 .cursor/skills/grafana-dev/scripts/grafana_dev.py reload-frontend
```
