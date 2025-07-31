#!/usr/bin/env python3

import os

import modal

# Use the 2025.06 Modal Image Builder which avoids the need to install Modal client
# dependencies into the container image.

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

# Here's a basic Dockerfile that installs docker with buildx and ensures
# that the docker daemon is started with the correct network configuration
# upon modal.Sandbox startup.

dockerfile_content = """
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND="noninteractive"
RUN apt-get update
RUN apt-get install -y docker.io

# Install docker-buildx (non-legacy build system) and docker-compose
RUN apt-get update
RUN apt-get install ca-certificates curl
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc
# Add the repository to Apt sources:
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt-get update
RUN apt-get install docker-buildx-plugin
RUN apt-get install docker-compose-plugin
RUN mkdir /build

# Install additional tools for network testing
RUN apt-get install -y wget curl iputils-ping dnsutils

# Start docker daemon
COPY start-dockerd.sh .
"""

start_dockerd_sh_content = """#!/bin/bash
set -xe -o pipefail

dev=$(ip route show default | awk '/default/ {print $5}')
if [ -z "$dev" ]; then
    echo "Error: No default device found."
    ip route show
    exit 1
else
    echo "Default device: $dev"
fi
addr=$(ip addr show dev "$dev" | grep -w inet | awk '{print $2}' | cut -d/ -f1)
if [ -z "$addr" ]; then
    echo "Error: No IP address found for device $dev."
    ip addr show dev "$dev"
    exit 1
else
    echo "IP address for $dev: $addr"
fi

echo 1 > /proc/sys/net/ipv4/ip_forward
iptables-legacy -t nat -A POSTROUTING -o "$dev" -j SNAT --to-source "$addr" -p tcp
iptables-legacy -t nat -A POSTROUTING -o "$dev" -j SNAT --to-source "$addr" -p udp

exec /usr/bin/dockerd --iptables=false --ip6tables=false -D"""

# Write the Dockerfile content to a local file.
with open("Dockerfile.docker_in_gvisor", "w") as dockerfile:
    dockerfile.write(dockerfile_content)

# Write the start-dockerd.sh content to a local file.
with open("start-dockerd.sh", "w") as start_dockerd_sh:
    start_dockerd_sh.write(start_dockerd_sh_content)
os.chmod("start-dockerd.sh", 0o755)


dockerfile_image = modal.Image.from_dockerfile("Dockerfile.docker_in_gvisor")


def test_network_mode(sb, mode):
    """Test a specific Docker network mode"""
    print(f"\n--- Testing {mode} network mode ---")
    
    # Run container with specific network mode
    if mode == "bridge":
        cmd = ["docker", "run", "--rm", "--name", f"test-{mode}", "alpine", "sh", "-c", 
               "nslookup google.com && wget -q -O- http://google.com | head -n 1"]
    elif mode == "host":
        cmd = ["docker", "run", "--rm", "--network", "host", "--name", f"test-{mode}", "alpine", "sh", "-c",
               "nslookup google.com && wget -q -O- http://google.com | head -n 1"]
    elif mode == "none":
        cmd = ["docker", "run", "--rm", "--network", "none", "--name", f"test-{mode}", "alpine", "sh", "-c",
               "nslookup google.com || echo 'No network as expected'"]
    
    p = sb.exec(*cmd)
    output = p.stdout.read()
    print(output)
    p.wait()
    
    if p.returncode == 0:
        print(f"{mode}: PASS")
        return True
    else:
        print(f"{mode}: FAIL")
        print(p.stderr.read())
        return False


def test_docker_compose_egress(sb):
    """Test egress connectivity with docker-compose bridge network (PyPI package install)"""
    print(f"\n--- Testing docker-compose-bridge with PyPI egress ---")
    
    # Create a simple docker-compose.yml that tests PyPI connectivity
    compose_content = """services:
  pypi-test:
    image: python:3.11-slim
    command: ["sh", "-c", "echo 'Testing PyPI connectivity...' && pip install --no-cache-dir requests==2.31.0 && python -c 'import requests; print(\\\"Successfully installed and imported requests\\\")' && echo 'Testing general HTTPS egress...' && python -c 'import urllib.request; print(urllib.request.urlopen(\\\"https://pypi.org\\\").status)'"]
    networks:
      - test-network

networks:
  test-network:
    driver: bridge
"""
    
    with sb.open("/tmp/docker-compose-test.yml", "w") as f:
        f.write(compose_content)
    
    print("Starting docker-compose service...")
    p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-test.yml", "up", "--abort-on-container-exit")
    
    output = []
    for line in p.stdout:
        print(line, end="")
        output.append(line)
    
    p.wait()
    
    # If it failed, check stderr
    if p.returncode != 0:
        print("\nSTDERR output:")
        stderr = p.stderr.read()
        print(stderr)
        
        # Get logs from the container
        print("\nGetting container logs...")
        logs_p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-test.yml", "logs")
        logs = logs_p.stdout.read()
        print(logs)
        logs_p.wait()
    
    # Check if pip install succeeded
    success = any("Successfully installed and imported requests" in line for line in output)
    
    # Clean up
    print("\nCleaning up docker-compose...")
    p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-test.yml", "down", "-v")
    p.wait()
    
    if success:
        print("docker-compose-bridge egress: PASS")
        return True
    else:
        print("docker-compose-bridge egress: FAIL")
        return False


def test_docker_compose_host_network(sb):
    """Test docker-compose with host network mode"""
    print(f"\n--- Testing docker-compose with host network ---")
    
    # Create a docker-compose.yml that uses host network
    compose_content = """services:
  pypi-test-host:
    image: python:3.11-slim
    network_mode: host
    command: ["sh", "-c", "echo 'Testing PyPI connectivity with host network...' && pip install --no-cache-dir requests==2.31.0 && python -c 'import requests; print(\\\"Successfully installed and imported requests with host network\\\")' && echo 'Testing general HTTPS egress...' && python -c 'import urllib.request; print(urllib.request.urlopen(\\\"https://pypi.org\\\").status)'"]
"""
    
    with sb.open("/tmp/docker-compose-host-test.yml", "w") as f:
        f.write(compose_content)
    
    print("Starting docker-compose service with host network...")
    p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-host-test.yml", "up", "--abort-on-container-exit")
    
    output = []
    for line in p.stdout:
        print(line, end="")
        output.append(line)
    
    p.wait()
    
    # If it failed, check stderr
    if p.returncode != 0:
        print("\nSTDERR output:")
        stderr = p.stderr.read()
        print(stderr)
        
        # Get logs from the container
        print("\nGetting container logs...")
        logs_p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-host-test.yml", "logs")
        logs = logs_p.stdout.read()
        print(logs)
        logs_p.wait()
    
    # Check if pip install succeeded
    success = any("Successfully installed and imported requests with host network" in line for line in output)
    
    # Clean up
    print("\nCleaning up docker-compose...")
    p = sb.exec("docker", "compose", "-f", "/tmp/docker-compose-host-test.yml", "down", "-v")
    p.wait()
    
    if success:
        print("docker-compose host network: PASS")
        return True
    else:
        print("docker-compose host network: FAIL")
        return False


def test_docker_compose_local():
    """Test docker-compose locally (outside Modal) for comparison"""
    print("\n--- Testing docker-compose-bridge locally (outside Modal) ---")
    
    # Same docker-compose content as the Modal test
    compose_content = """services:
  pypi-test:
    image: python:3.11-slim
    command: ["sh", "-c", "echo 'Testing PyPI connectivity...' && pip install --no-cache-dir requests==2.31.0 && python -c 'import requests; print(\\\"Successfully installed and imported requests\\\")' && echo 'Testing general HTTPS egress...' && python -c 'import urllib.request; print(urllib.request.urlopen(\\\"https://pypi.org\\\").status)'"]
    networks:
      - test-network

networks:
  test-network:
    driver: bridge
"""
    
    # Write to local file
    with open("/tmp/docker-compose-local-test.yml", "w") as f:
        f.write(compose_content)
    
    print("Starting docker-compose service locally...")
    import subprocess
    
    # Run docker-compose locally
    result = subprocess.run(
        ["docker", "compose", "-f", "/tmp/docker-compose-local-test.yml", "up", "--abort-on-container-exit"],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    # Check if pip install succeeded
    success = "Successfully installed and imported requests" in result.stdout
    
    # Clean up
    print("\nCleaning up local docker-compose...")
    subprocess.run(
        ["docker", "compose", "-f", "/tmp/docker-compose-local-test.yml", "down", "-v"],
        capture_output=True
    )
    
    # Clean up file
    import os
    os.remove("/tmp/docker-compose-local-test.yml")
    
    if success:
        print("LOCAL docker-compose-bridge egress: PASS")
        return True
    else:
        print("LOCAL docker-compose-bridge egress: FAIL")
        return False


def main():
    # First test locally for comparison
    print("=" * 60)
    print("TESTING DOCKER-COMPOSE LOCALLY (for comparison)")
    print("=" * 60)
    local_result = test_docker_compose_local()
    
    print("\n" + "=" * 60)
    print("TESTING IN MODAL SANDBOX")
    print("=" * 60)
    
    print("\nLooking up modal.Sandbox app")
    app = modal.App.lookup("docker-network-test", create_if_missing=True)
    print("Creating sandbox")

    with modal.enable_output():
        sb = modal.Sandbox.create(
            "/start-dockerd.sh",
            timeout=60 * 60,
            app=app,
            image=dockerfile_image,
            experimental_options={"enable_docker_in_gvisor": True},
        )

    # Wait for Docker to be ready
    import time
    for i in range(10):
        p = sb.exec("docker", "ps")
        p.wait()
        if p.returncode == 0:
            break
        time.sleep(1)

    # Pull alpine image
    print("Pulling alpine image")
    p = sb.exec("docker", "pull", "alpine")
    for l in p.stdout:
        print(l, end="")
    p.wait()
    
    # Test different network modes
    print("\nTesting Docker network modes:")
    print("=============================")
    
    results = {}
    for mode in ["bridge", "host", "none"]:
        results[mode] = test_network_mode(sb, mode)
    
    # Test docker-compose with egress
    results["docker-compose-bridge"] = test_docker_compose_egress(sb)
    
    # Test docker-compose with host network
    results["docker-compose-host"] = test_docker_compose_host_network(sb)
    
    # Summary
    print("\n=== SUMMARY ===")
    print(f"LOCAL docker-compose-bridge: {'PASS' if local_result else 'FAIL'} (baseline)")
    print("--- Modal Sandbox Results ---")
    for mode, passed in results.items():
        print(f"{mode}: {'PASS' if passed else 'FAIL'}")
    
    sb.terminate()


if __name__ == "__main__":
    main()