import os

import modal

os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

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
    app = modal.App.lookup("no-dockerd-snapshot", create_if_missing=True)
    print("Creating sandbox with docker-in-gvisor but without starting dockerd")

    with modal.enable_output():
        # Use sleep infinity instead of starting dockerd
        sb = modal.Sandbox.create(
            "sleep",
            "infinity",
            timeout=60 * 60,
            app=app,
            image=dockerfile_image,
            experimental_options={"enable_docker_in_gvisor": True},
        )

    print("Sandbox created and running (dockerd NOT started)")
    
    # Sleep for 5 seconds to test if it's a timing issue
    print("Sleeping for 5 seconds...")
    import time
    time.sleep(5)
    print("Sleep complete")
    
    print("Attempting to create snapshot...")
    image = sb.snapshot_filesystem()
    print("Snapshot created successfully!")
    print(f"Snapshot image: {image}")
    
    sb.terminate()
    print("Sandbox terminated")


if __name__ == "__main__":
    main()