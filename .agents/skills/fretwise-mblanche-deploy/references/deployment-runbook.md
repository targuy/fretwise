# FretWise mblanche Deployment Runbook

## Preconditions

- Windows checkout: `D:\DocumentsBenoit\pythonProject\fretwise`
- SSH alias: `mblanche`
- Production Compose: `docker/compose.web.yml`
- Server root: `/volume2/docker/fretwise`
- Release source: committed `HEAD`; use `git archive`, never a broad working-tree copy.

Do not deploy an uncommitted or dirty worktree. The command below records the
release tag locally before any server mutation:

```powershell
$releaseTag = "$(Get-Date -Format yyyyMMdd-HHmmss)-$(rtk git rev-parse --short HEAD)"
rtk git status --short
rtk git log -1 --oneline
```

The status must be clean. Run the tests selected for the change. For UI work,
also run the local browser scenario before continuing.

## Inspect Current Runtime

```powershell
rtk ssh mblanche "set -eu; readlink -f /volume2/docker/fretwise/current; sudo docker compose -f /volume2/docker/fretwise/current/docker/compose.web.yml ps"
```

Save output path as rollback target. Docker access normally requires `sudo`.

## Create Release

Create empty release, carry only release-local Compose settings forward, then
archive committed source into it. This avoids stale deleted files and leaves
runtime mounts untouched.

```powershell
rtk ssh mblanche "set -eu; release=/volume2/docker/fretwise/releases/$releaseTag; test ! -e \"`$release\"; sudo install -d -m 0755 \"`$release\"; sudo install -D -m 0644 /volume2/docker/fretwise/current/docker/.env \"`$release/docker/.env\""
rtk proxy git archive --format=tar HEAD | rtk proxy ssh mblanche "set -eu; sudo tar -xf - -C /volume2/docker/fretwise/releases/$releaseTag"
```

If Git archive lacks a required new file, stop. Commit it, then restart with a
new tag. Do not patch production release from an untracked local file.

## Build and Start

Set image tag inside release-local `docker/.env`; Compose resolves that file
beside `compose.web.yml`.

```powershell
rtk ssh mblanche "set -eu; release=/volume2/docker/fretwise/releases/$releaseTag; image=fretwise-web:$releaseTag; envfile=\"`$release/docker/.env\"; if sudo grep -q '^FRETWISE_IMAGE=' \"`$envfile\"; then sudo sed -i \"s|^FRETWISE_IMAGE=.*|FRETWISE_IMAGE=`$image|\" \"`$envfile\"; else printf '%s\n' \"FRETWISE_IMAGE=`$image\" | sudo tee -a \"`$envfile\" >/dev/null; fi; cd \"`$release\"; sudo docker compose -f docker/compose.web.yml config --quiet; sudo docker compose -f docker/compose.web.yml build web; sudo docker compose -f docker/compose.web.yml up -d --no-deps --force-recreate web"
```

`--no-deps` leaves Cloudflare tunnel running. Do not rebuild model image unless
the model bundle changed and Docker build requirements were verified.

## Health, Promote, Verify

Wait bounded time. Leave `current` unchanged until health succeeds.

```powershell
rtk ssh mblanche "set -eu; release=/volume2/docker/fretwise/releases/$releaseTag; for attempt in `$(seq 1 18); do if curl -fsS http://127.0.0.1:8080/health/ready; then break; fi; if [ \"`$attempt\" -eq 18 ]; then exit 1; fi; sleep 5; done; cd \"`$release\"; sudo docker compose -f docker/compose.web.yml ps; sudo ln -s \"`$release\" /volume2/docker/fretwise/current.next; sudo mv -Tf /volume2/docker/fretwise/current.next /volume2/docker/fretwise/current"
Invoke-WebRequest -UseBasicParsing 'https://fretwise.mblanche.direct.ug.link/health/ready' | Select-Object -ExpandProperty Content
```

For changed static assets, retrieve exact asset URL from LAN endpoint and check
a stable marker from the new revision. For functional work, execute its user
scenario against the LAN URL.

## Rollback

Use only after failure following promotion. Replace `<known-good-release>` with
the prior absolute release path captured during inspection.

```powershell
rtk ssh mblanche "set -eu; release='<known-good-release>'; test -f \"`$release/docker/compose.web.yml\"; sudo ln -s \"`$release\" /volume2/docker/fretwise/current.rollback; sudo mv -Tf /volume2/docker/fretwise/current.rollback /volume2/docker/fretwise/current; cd \"`$release\"; sudo docker compose -f docker/compose.web.yml up -d --no-deps --force-recreate web; curl -fsS http://127.0.0.1:8080/health/ready"
```

Do not remove failed releases automatically. Preserve evidence for diagnosis;
prune releases only under an explicit retention decision.
