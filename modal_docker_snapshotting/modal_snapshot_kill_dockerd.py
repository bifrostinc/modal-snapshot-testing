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


def main():
    print("Looking up modal.Sandbox app")
    app = modal.App.lookup("docker-kill-demo", create_if_missing=True)
    print("Creating sandbox")

    with modal.enable_output():
        # Use sleep infinity as init command instead of start-dockerd.sh
        sb = modal.Sandbox.create(
            "sleep",
            "infinity",
            timeout=60 * 60,
            app=app,
            image=dockerfile_image,
            experimental_options={"enable_docker_in_gvisor": True},
        )

    print("Sandbox created with sleep infinity")
    
    # Start dockerd manually in the background
    print("Starting dockerd in the background...")
    p = sb.exec("bash", "-c", "/start-dockerd.sh &")
    p.wait()
    
    # Wait a bit for dockerd to start
    print("Waiting for dockerd to start...")
    import time
    time.sleep(5)
    
    # Verify dockerd is running
    print("Checking dockerd status...")
    p = sb.exec("bash", "-c", "ps aux | grep dockerd | grep -v grep")
    output = p.stdout.read()
    print(f"Dockerd process: {output}")
    p.wait()

    # Here's a simple Dockerfile that we'll build and run within Modal.
    dockerfile = """
    FROM ubuntu
    RUN apt-get update
    RUN apt-get install -y cowsay curl
    RUN mkdir -p /usr/share/cowsay/cows/
    RUN curl -o /usr/share/cowsay/cows/docker.cow https://raw.githubusercontent.com/docker/whalesay/master/docker.cow
    ENTRYPOINT ["/usr/games/cowsay", "-f", "docker.cow"]
    """
    with sb.open("/build/Dockerfile", "w") as f:
        f.write(dockerfile)

    print("Building docker image")
    p = sb.exec("docker", "build", "--network=host", "-t", "whalesay", "/build")
    for l in p.stdout:
        print(l, end="")
    p.wait()
    print("--------------------------------")
    if p.returncode != 0:
        print(p.stderr.read())
        raise Exception("Docker build failed")

    # Get the Sandbox to run the built image and show this:
    #
    #  ________
    # < Hello! >
    #  --------
    #     \
    #      \
    #       \
    #                     ##         .
    #               ## ## ##        ==
    #            ## ## ## ## ##    ===
    #        /"""""""""""""""""\___/ ===
    #       {                       /  ===-
    #        \______ O           __/
    #          \    \         __/
    #           \____\_______/

    print("Running Docker image")
    # Note we can't use -it here because we're not in a TTY.
    p = sb.exec("docker", "run", "--rm", "whalesay", "Hello!")
    reply = p.stdout.read()
    print(reply)
    p.wait()
    if p.returncode != 0:
        raise Exception(f"Docker run failed: {p.stderr.read()}")
    
    # Kill dockerd gracefully before attempting snapshot
    print("Killing dockerd gracefully...")
    p = sb.exec("bash", "-c", "pkill dockerd || true")
    p.wait()
    
    # Kill containerd as well
    print("Killing containerd gracefully...")
    p = sb.exec("bash", "-c", "pkill containerd || true")
    p.wait()
    
    # Wait a moment to ensure they're dead
    time.sleep(2)
    
    # Verify dockerd and containerd are killed
    print("Verifying dockerd and containerd are killed...")
    p = sb.exec("bash", "-c", "ps aux | grep -E 'dockerd|containerd' | grep -v grep || echo 'dockerd/containerd not found'")
    output = p.stdout.read()
    print(f"Process check: {output}")
    p.wait()
    
    # Find and print all .sock files
    print("\nFinding all .sock files in the filesystem...")
    find_cmd = sb.exec("bash", "-c", "find / -name '*.sock' -type s 2>/dev/null || true")
    sock_files = find_cmd.stdout.read().strip()
    find_cmd.wait()
    
    if sock_files:
        sock_list = sock_files.split('\n')
        print(f"Found {len(sock_list)} socket files:")
        for sock in sock_list:
            if sock:  # Skip empty lines
                print(f"  - {sock}")
    else:
        print("No socket files found")
    
    # Delete all socket files
    print("\nDeleting all socket files...")
    delete_cmd = sb.exec("bash", "-c", "find / -name '*.sock' -type s 2>/dev/null | xargs -r rm -f")
    delete_cmd.wait()
    
    # Verify deletion
    print("Verifying socket files are deleted...")
    verify_cmd = sb.exec("bash", "-c", "find / -name '*.sock' -type s 2>/dev/null | wc -l")
    remaining_count = verify_cmd.stdout.read().strip()
    verify_cmd.wait()
    print(f"Remaining socket files: {remaining_count}")

    print("Creating snapshot")
    image = sb.snapshot_filesystem()
    print("Snapshot created")
    print(image)
    sb.terminate()
    print("Sandbox terminated")


if __name__ == "__main__":
    main()