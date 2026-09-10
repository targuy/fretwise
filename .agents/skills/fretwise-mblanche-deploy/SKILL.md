---
name: fretwise-mblanche-deploy
description: Deploy a validated FretWise web release to mblanche through immutable Docker releases, then verify health and LAN access. Use after FretWise web or backend development when the user requests delivery, deployment, publication, or a final runtime check. Do not use for desktop-only work or when no server validation is needed.
---

# Fretwise Mblanche Deploy

## Purpose

Deliver the exact validated FretWise web revision to the NAS without mutating
state, credentials, or the previous release. Runtime data stays under
`/volume2/docker/fretwise/state` and `/volume1/gp`; releases contain application
code only.

## Before Deployment

1. Inspect `Dockerfile`, `docker/compose.web.yml`, `pixi.toml`, and current Git
   status. Preserve unrelated changes.
2. Run targeted tests for the change. Run a local browser check for user-visible
   web work.
3. Production deploy requires a committed, auditable revision. If the worktree
   is dirty, do not package it as a release; identify the remaining changes and
   ask for a clean commit or explicit direction.
4. Read [deployment runbook](references/deployment-runbook.md) before mutating
   `mblanche`.

## Deployment Rules

- Use `docker/compose.web.yml`, never legacy Compose files.
- Create `/volume2/docker/fretwise/releases/<tag>`; never edit a prior release.
- Preserve `docker/.env` from current release, update only `FRETWISE_IMAGE` in
  the new release before building.
- Build and start from the new release path. Change `current` only after
  `/health/ready` succeeds.
- Verify: Compose config, running image tag, readiness endpoint, and LAN URL.
- On failed build, startup, or health check, keep `current` unchanged. Report
  failure and use runbook rollback only after identifying a known-good release.
- Never copy or print shared environment files, tunnel token, auth data,
  partitions, cache, sounds, pedals, or model images.

## Finish

For a delivery request, perform the release and report release tag, image tag,
health state, LAN verification, and rollback target. For a development request
without delivery authority, run preflight/readiness checks and state that no
production mutation was made.
