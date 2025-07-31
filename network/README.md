# Docker Network Modes Test

This test suite evaluates Docker network connectivity and egress behavior across different network modes when running in Modal's Docker-in-gvisor environment.

## What This Tests

The test suite runs identical network connectivity tests both locally (as a baseline) and within a Modal sandbox to identify any network-related issues specific to the Modal environment. It tests:

1. **Basic Docker Network Modes**:
   - `bridge` - Default Docker network with NAT
   - `host` - Container shares host's network namespace
   - `none` - Isolated container with no network access

2. **Docker Compose Network Modes**:
   - `docker-compose-bridge` - Docker Compose using default bridge network
   - `docker-compose-host` - Docker Compose using host network mode

Each test performs egress connectivity checks including:
- DNS resolution (nslookup)
- HTTP/HTTPS connectivity (wget/curl)
- Package downloads (pip install from PyPI)

## Test Results

```
=== SUMMARY ===
LOCAL docker-compose-bridge: PASS (baseline)
--- Modal Sandbox Results ---
bridge: PASS
host: PASS
none: PASS
docker-compose-bridge: FAIL
docker-compose-host: PASS
```

## Key Findings

- **Local baseline**: Docker Compose with bridge network works correctly on the local machine
- **Modal sandbox**: Basic Docker commands work with all network modes
- **Issue identified**: Docker Compose with bridge network fails egress connectivity in Modal sandbox
- **Workaround**: Docker Compose with host network mode works correctly in Modal sandbox

This suggests there may be an issue with how Docker Compose configures bridge networks within the Modal Docker-in-gvisor environment, particularly affecting egress traffic like package downloads from PyPI.

## Failing Docker Compose Configuration

The following docker-compose.yml configuration fails in Modal sandbox but works locally:

```yaml
services:
  pypi-test:
    image: python:3.11-slim
    command: ["sh", "-c", "echo 'Testing PyPI connectivity...' && pip install --no-cache-dir requests==2.31.0 && python -c 'import requests; print(\"Successfully installed and imported requests\")' && echo 'Testing general HTTPS egress...' && python -c 'import urllib.request; print(urllib.request.urlopen(\"https://pypi.org\").status)'"]
    networks:
      - test-network

networks:
  test-network:
    driver: bridge
```

This configuration attempts to:
1. Download and install a Python package from PyPI
2. Test HTTPS connectivity to pypi.org

The same configuration works when using `network_mode: host` instead of a bridge network.

## Running the Test

```bash
./network/modal_docker_network_modes_test.py
```

The test will:
1. First run a local Docker Compose test as a baseline
2. Create a Modal sandbox with Docker-in-gvisor enabled
3. Test each network mode and report results
4. Provide a summary comparing local vs Modal sandbox behavior