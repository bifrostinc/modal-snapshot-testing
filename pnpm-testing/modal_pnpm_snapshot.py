import os
import time
import modal

# Use the 2025.06 Modal Image Builder
os.environ["MODAL_IMAGE_BUILDER_VERSION"] = "2025.06"

# Build the Docker image with pnpm and Slidev repository
dockerfile_image = modal.Image.from_dockerfile("./pnpm-testing/Dockerfile.pnpm")


def main():
    print("=" * 60)
    print("PNPM Snapshotting Bug Reproduction Test")
    print("=" * 60)

    print("\n1. Looking up/creating Modal app...")
    app = modal.App.lookup("pnpm-snapshot-test", create_if_missing=True)

    print("2. Creating sandbox with Docker-in-gvisor enabled...")
    start_time = time.time()

    with modal.enable_output():
        sb = modal.Sandbox.create(
            "/start-dockerd.sh",
            timeout=60 * 60,  # 1 hour timeout
            app=app,
            image=dockerfile_image,
            experimental_options={"enable_docker_in_gvisor": True},
        )

    print(f"   Sandbox created in {time.time() - start_time:.2f}s")

    # Wait for Docker daemon to be ready
    print("\n3. Waiting for Docker daemon to initialize...")
    time.sleep(5)

    # Verify Docker is running
    print("4. Verifying Docker daemon status...")
    p = sb.exec("docker", "version")
    docker_version = p.stdout.read()
    p.wait()
    print(f"   Docker status: {'Running' if p.returncode == 0 else 'Failed'}")
    if p.returncode != 0:
        print(f"   Error: {p.stderr.read()}")
        sb.terminate()
        return

    # Check the Slidev repo structure
    print("\n5. Checking Slidev repository structure...")
    p = sb.exec("ls", "-la", "/workspace/slidev")
    print("   Repository contents:")
    for line in p.stdout:
        print(f"   {line}", end="")

    # Count packages before install
    print("\n6. Analyzing package.json files...")
    p = sb.exec("find", "/workspace/slidev", "-name", "package.json", "-type", "f")
    package_files = list(p.stdout)
    print(f"   Found {len(package_files)} package.json files")

    # Run pnpm install
    print("\n7. Running pnpm install...")
    install_start = time.time()
    p = sb.exec("bash", "-c", "cd /workspace/slidev && pnpm install")

    # Stream output
    line_count = 0
    for line in p.stdout:
        if line_count < 20:  # Show first 20 lines
            print(f"   {line}", end="")
        line_count += 1

    p.wait()
    install_duration = time.time() - install_start

    if p.returncode != 0:
        print(f"   ERROR: pnpm install failed with code {p.returncode}")
        print(f"   stderr: {p.stderr.read()}")
    else:
        print(f"   pnpm install completed successfully in {install_duration:.2f}s")
        print(f"   Total output lines: {line_count}")

    # Check node_modules size
    print("\n8. Checking installed packages...")
    p = sb.exec(
        "bash",
        "-c",
        "find /workspace/slidev -name node_modules -type d | xargs du -sh 2>/dev/null | tail -5",
    )
    for line in p.stdout:
        print(f"   {line}", end="")

    # Count total packages installed
    p = sb.exec(
        "bash",
        "-c",
        "find /workspace/slidev -path '*/node_modules/*' -name package.json | wc -l",
    )
    package_count = p.stdout.read().strip()
    print(f"   Total packages installed: {package_count}")

    # Attempt to create a snapshot
    print("\n9. Attempting to create filesystem snapshot...")
    snapshot_start = time.time()

    try:
        image = sb.snapshot_filesystem()
        snapshot_duration = time.time() - snapshot_start
        print(f"   SUCCESS: Snapshot created in {snapshot_duration:.2f}s")
        print(f"   Snapshot image: {image}")
    except Exception as e:
        snapshot_duration = time.time() - snapshot_start
        print(f"   FAILED: Snapshot failed after {snapshot_duration:.2f}s")
        print(f"   Error: {str(e)}")
        print(f"   Error type: {type(e).__name__}")

    # Clean up
    print("\n10. Terminating sandbox...")
    sb.terminate()
    print("    Sandbox terminated")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("Repository: Slidev (presentation framework)")
    print("Package manager: pnpm")
    print(f"Packages installed: {package_count}")
    print(f"Install duration: {install_duration:.2f}s")
    print(f"Snapshot attempt: {'SUCCESS' if 'image' in locals() else 'FAILED'}")
    if "image" in locals():
        print(f"Snapshot duration: {snapshot_duration:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
