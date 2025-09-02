# PNPM Snapshotting Bug Reproduction

This test reproduces a Modal filesystem snapshotting failure that occurs when using pnpm to install packages in a Docker-in-gvisor environment.

## Running the Test

```bash
uv run pnpm-testing/modal_pnpm_snapshot.py
```


## Test Setup

- **Repository**: Slidev (https://github.com/slidevjs/slidev)
  - Medium-sized pnpm monorepo
  - ~50-100 direct dependencies
  - Presentation framework built with Vue
  
- **Environment**: 
  - Modal Sandbox with `enable_docker_in_gvisor: True`
  - Docker daemon running inside the sandbox
  - Node.js 22 with pnpm latest

## Files

- `modal_pnpm_snapshot.py` - Main test script that:
  1. Creates a Modal sandbox with Docker-in-gvisor
  2. Starts Docker daemon
  3. Runs `pnpm install` in the Slidev repository
  4. Attempts to create a filesystem snapshot
  5. Reports success/failure with timing metrics

- `Dockerfile.pnpm` - Docker image that includes:
  - Node.js 22
  - Docker and docker-compose
  - pnpm package manager
  - Pre-cloned Slidev repository
  - Network utilities (iproute2, iptables)

- `start-dockerd.sh` - Script to initialize Docker daemon with proper networking
