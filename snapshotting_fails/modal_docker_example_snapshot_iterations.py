import os
import sys
import time

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


def setup_and_run_docker_image(sb):
    """Pull and run a pre-built Docker image."""
    # Use a pre-built image instead of building one
    print("Pulling pre-built Docker image (hello-world)")
    p = sb.exec("docker", "pull", "hello-world")
    for l in p.stdout:
        print(l, end="")
    p.wait()
    print("--------------------------------")
    if p.returncode != 0:
        print(p.stderr.read())
        raise Exception("Docker pull failed")

    # Run the Docker image once to verify it works
    print("Running Docker image")
    p = sb.exec("docker", "run", "--rm", "hello-world")
    reply = p.stdout.read()
    print(reply[:500] if len(reply) > 500 else reply)  # Truncate if too long
    p.wait()
    if p.returncode != 0:
        raise Exception(f"Docker run failed: {p.stderr.read()}")


def attempt_snapshot(sb, iteration):
    """Attempt to create a snapshot and return success/failure status."""
    print(f"\n=== Iteration {iteration} ===")
    print("Creating snapshot")

    try:
        image = sb.snapshot_filesystem()
        print("Snapshot created")
        print(image)
        return True, None
    except modal.exception.ExecutionError as e:
        print(f"Snapshot failed: {e}")
        return False, str(e)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False, str(e)


def main():
    # Parse command line arguments
    iterations = 10  # Default
    if len(sys.argv) > 1:
        try:
            iterations = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of iterations: {sys.argv[1]}")
            sys.exit(1)

    print(f"Running {iterations} iterations of snapshot testing")
    print("=" * 50)

    # Statistics tracking
    successes = 0
    failures = 0
    failure_messages = []

    print("Looking up modal.Sandbox app")
    app = modal.App.lookup("docker-demo", create_if_missing=True)

    try:
        # Run multiple iterations of create sandbox / snapshot filesystem
        for i in range(1, iterations + 1):
            # For iterations after the first, create a new sandbox
            print(f"\nCreating new sandbox for iteration {i}")
            with modal.enable_output():
                sb = modal.Sandbox.create(
                    "/start-dockerd.sh",
                    timeout=60 * 60,
                    app=app,
                    image=dockerfile_image,
                    experimental_options={"enable_docker_in_gvisor": True},
                )

            # Wait a moment for Docker daemon to fully initialize
            print("Waiting for Docker daemon to initialize")
            time.sleep(10)

            # Pull and run the Docker image again (it should be fast since it's small)
            setup_and_run_docker_image(sb)

            # Attempt snapshot
            success, error_msg = attempt_snapshot(sb, i)

            if success:
                successes += 1
            else:
                failures += 1
                failure_messages.append(f"Iteration {i}: {error_msg}")

            # Terminate sandbox after each iteration
            try:
                sb.terminate()
                print("Sandbox terminated")
            except Exception as e:
                print(f"Error terminating sandbox: {e}")

            # Small delay between iterations
            if i < iterations:
                time.sleep(2)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception:
        raise

    # Print statistics
    total = successes + failures
    if total == 0:
        print("\n" + "=" * 50)
        print("No iterations were completed")
        print("=" * 50)
        return

    print("\n" + "=" * 50)
    print("RESULTS SUMMARY")
    print("=" * 50)
    print(f"Total iterations: {total}")
    print(f"Successes: {successes} ({successes/total*100:.1f}%)")
    print(f"Failures: {failures} ({failures/total*100:.1f}%)")

    if failure_messages:
        print("\nFailure details:")
        for msg in failure_messages:
            print(f"  - {msg}")


if __name__ == "__main__":
    main()
