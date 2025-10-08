#!/usr/bin/env python3
import os
import sys
import modal

# Use the 2025.06 Modal Image Builder which avoids the need to install Modal client
# dependencies into the container image.
os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"


def main():
    if len(sys.argv) != 3:
        print("Usage: python run-docker-compose.py <image_id> <docker-compose.yml>")
        sys.exit(1)

    image_id = sys.argv[1]
    docker_compose_file = sys.argv[2]

    if not os.path.exists(docker_compose_file):
        print(f"Error: Docker compose file not found: {docker_compose_file}")
        sys.exit(1)

    # Read the docker-compose file content
    with open(docker_compose_file, "r") as f:
        docker_compose_content = f.read()

    # Create Modal image from the provided image ID
    dockerfile_image = modal.Image.from_registry(image_id)

    print("Looking up modal.Sandbox app")
    app = modal.App.lookup("docker-compose-demo", create_if_missing=True)
    print("Creating sandbox")

    with modal.enable_output():
        sb = modal.Sandbox.create(
            "/start-dockerd.sh",
            timeout=60 * 60,
            app=app,
            image=dockerfile_image,
            experimental_options={"enable_docker_in_gvisor": True},
        )

    # Copy docker-compose file into the sandbox
    print("Copying docker-compose file to sandbox")
    with sb.open("/docker-compose.yml", "w") as f:
        f.write(docker_compose_content)

    # Output package versions
    print("\n=== Package Versions ===")
    packages = [
        ("curl", "curl --version"),
        ("wget", "wget --version"),
        ("git", "git --version"),
        ("gcc", "gcc --version"),
        ("gnupg", "gpg --version"),
        ("python3", "python3 --version"),
        ("pip", "pip3 --version"),
        ("docker", "docker --version"),
        ("iptables", "iptables --version"),
        ("ripgrep", "rg --version"),
    ]

    for name, cmd in packages:
        print(f"\n{name}:")
        p = sb.exec("sh", "-c", f"{cmd} | head -1")
        print(p.stdout.read().strip())
    print("========================\n")

    # Run docker-compose up
    print("Running docker-compose up")
    p = sb.exec("docker-compose", "-p", "docker-compose-demo", "up")
    for l in p.stdout:
        print(l, end="")
    p.wait()

    if p.returncode != 0:
        print("docker-compose up failed:")
        print(p.stderr.read())
        sb.terminate()
        sys.exit(1)

    print("--------------------------------")
    print("Docker Compose services started successfully")
    print("\nTo view logs, use: docker-compose logs")
    print("To stop services, use: docker-compose down")
    print("\nSandbox ID:", sb.object_id)
    print("Sandbox will remain active for 1 hour")

    # Keep the sandbox running
    print("\nPress Ctrl+C to terminate the sandbox")
    try:
        sb.wait()
    except KeyboardInterrupt:
        print("\nTerminating sandbox...")
        sb.terminate()


if __name__ == "__main__":
    main()
