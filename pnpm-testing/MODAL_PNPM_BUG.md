# Modal Sandbox pnpm Snapshot Regression

## Overview

When we take a filesystem snapshot of a sandbox that has just completed a `pnpm install`, resume from that snapshot, and attempt to run `pnpm install --offline`, the install now fails because key packages are missing from `node_modules`. This regression started after the recent suspend/resume fixes landed – the sandbox can resume, but pnpm’s workspace no longer contains every package payload that was present before the snapshot.

## Environment

- **Modal**: Sandbox with `experimental_options.enable_docker_in_gvisor = true`
- **Image**: `pnpm-testing/Dockerfile.pnpm` (Node 22 + pnpm latest + Slidev repo pre-cloned)
- **Test harness**: `uv run pnpm-testing/modal_pnpm_snapshot.py`
- **App name**: `pnpm-snapshot-test`

## Reproduction Steps

1. Build the Docker image and create a sandbox via `modal.Sandbox.create("/start-dockerd.sh", …)`.
2. Inside the sandbox run `pnpm install` at the Slidev repo root.
3. Snapshot the sandbox filesystem (`sandbox.snapshot_filesystem()`).
4. Resume from the snapshot into a fresh sandbox (the script keeps it alive with `sleep infinity`).
5. Run validation inside the resumed sandbox:
   - Capture tracked `node_modules` entries (top-level names, `.pnpm` store entries, sampled manifest paths).
   - Attempt `pnpm install --offline` to ensure pnpm still sees all cached packages.

## Expected vs Observed

| Step | Expected | Observed |
| --- | --- | --- |
| Top-level `node_modules` entry count | 924 (same as before snapshot) | 920 after resume (four entries missing) |
| `.pnpm` store entry count | 1304 | 1304 (unchanged) |
| `pnpm install --offline` | Should succeed (all packages already cached) | **Fails** with `ENOENT` errors for `vite` and `esbuild` binaries |

## Evidence

```
Package.json count before suspend: 1445
Top-level entries sample before suspend: .bin, .modules.yaml, .pnpm, .pnpm-workspace-state-v1.json, @ampproject
Top-level entry count after resume: 920 (expected 924)
Tracked top entries present after resume: 5 / 5

pnpm install --offline output:
ENOENT: no such file or directory, open '/workspace/slidev/node_modules/.pnpm/vite@7.0.6_.../node_modules/vite/package.json'
WARN  Failed to create bin … node_modules/.pnpm/vite@7.0.6_.../node_modules/esbuild/bin/esbuild
WARN  Failed to create bin … node_modules/.pnpm/tsx@4.20.3/node_modules/esbuild/bin/esbuild
exit code: 1
```

Because the offline install fails, the test script now exits non-zero and reports `Node_modules validation: FAIL`.

## Notes

- The `.pnpm` store directory itself survives the snapshot/resume cycle (entry counts match), but the `node_modules/<package>` payloads are missing for certain packages – notably `vite` and `esbuild`, which are required bins.
- This failure reproduces consistently on multiple runs. Each run captures the snapshot metadata and logs the same `ENOENT` failures.
- The full reproduction script lives at `pnpm-testing/modal_pnpm_snapshot.py` and is part of the `conor.branagan/update-test-pnpm-suspend-resume` branch.
