# Modal Docker-in-gvisor Snapshot Testing

## Summary
Snapshots fail when dockerd has been started with `enable_docker_in_gvisor: True`. Even after killing dockerd/containerd and cleaning up socket files, snapshots still fail.

## Test Results

### Successful Snapshots
- `modal_simple_snapshot.py` - Basic sandbox without Docker
- `modal_snapshot_no_dockerd.py` - Docker-in-gvisor enabled but dockerd never started (requires 5s sleep)

### Failed Snapshots  
- `modal_docker_example_snapshot.py` - Dockerd running
- `modal_snapshot_kill_dockerd.py` - Dockerd started then killed, sockets cleaned (modal sockets preserved)
- `modal_snapshot_clean_sockets.py` - Dockerd running, non-modal sockets deleted
- `modal_snapshot_clean_all_sockets.py` - Dockerd running, all sockets deleted
- `modal_snapshot_no_dockerd_no_sleep.py` - Docker-in-gvisor enabled, no dockerd, no sleep

## Key Finding
Snapshots only succeed when:
1. Docker-in-gvisor is not used, OR
2. Docker-in-gvisor is enabled but dockerd is NEVER started

Starting dockerd creates persistent state that prevents snapshots, even after process termination and socket cleanup.

The 5-second sleep requirement suggests initialization timing issues when docker-in-gvisor is enabled.