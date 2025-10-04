import json
import os
import textwrap
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

    # Helper utilities for manifest generation and validation
    def run_python_json(sb_handle, script, step_description):
        print(f"\n{step_description}")
        command = "cd /workspace/slidev && python3 - <<'PY'\n" + script + "\nPY\n"
        proc = sb_handle.exec("bash", "-lc", command, timeout=600)
        stdout_text = proc.stdout.read()
        proc.wait()
        stderr_text = proc.stderr.read()

        if stdout_text.strip():
            for line in stdout_text.strip().splitlines():
                print(f"   {line}")
        if stderr_text.strip():
            print(f"   stderr: {stderr_text.strip()}")

        summary = None
        if stdout_text.strip():
            try:
                summary = json.loads(stdout_text.strip().splitlines()[-1])
            except json.JSONDecodeError:
                summary = {"raw_output": stdout_text.strip()}

        if proc.returncode != 0:
            print(f"   Command exited with code {proc.returncode}")

        return proc.returncode, summary

    manifest_script = textwrap.dedent(
        """
        import hashlib
        import json
        import os

        root = "node_modules"
        entries: list[list[str]] = []
        file_count = 0
        dir_count = 0
        symlink_count = 0

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for name in dirnames + filenames:
                full_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(full_path, root)
                if os.path.islink(full_path):
                    entries.append(["L", rel_path, os.readlink(full_path)])
                    symlink_count += 1
                elif os.path.isdir(full_path):
                    entries.append(["D", rel_path])
                    dir_count += 1
                else:
                    entries.append(["F", rel_path])
                    file_count += 1

        entries.sort()

        digest = hashlib.sha256()
        for entry in entries:
            digest.update("\0".join(entry).encode())

        manifest = {
            "entries": entries,
            "hash": digest.hexdigest(),
            "stats": {
                "files": file_count,
                "directories": dir_count,
                "symlinks": symlink_count,
            },
        }

        with open("node_modules_manifest.json", "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        print(json.dumps({
            "entry_count": len(entries),
            "hash": manifest["hash"],
            "stats": manifest["stats"],
        }))
        """
    )

    manifest_rc, manifest_summary = run_python_json(
        sb,
        manifest_script,
        "9. Recording node_modules manifest before suspend...",
    )

    if manifest_rc != 0:
        print("   ERROR: Failed to record node_modules manifest.")

    # Attempt to create a snapshot
    print("\n10. Attempting to create filesystem snapshot (simulated suspend)...")
    snapshot_start = time.time()

    resume_sb = None
    try:
        image = sb.snapshot_filesystem()
        snapshot_duration = time.time() - snapshot_start
        print(f"   SUCCESS: Snapshot created in {snapshot_duration:.2f}s")
        print(f"   Snapshot image: {image}")

        print("\n11. Terminating original sandbox before resume...")
        sb.terminate()
        print("    Original sandbox terminated")

        print("\n12. Creating resumed sandbox from snapshot image...")
        resume_start = time.time()
        with modal.enable_output():
            resume_sb = modal.Sandbox.create(
                "/start-dockerd.sh",
                timeout=60 * 60,
                app=app,
                image=image,
                experimental_options={"enable_docker_in_gvisor": True},
            )
        print(f"   Resumed sandbox ready in {time.time() - resume_start:.2f}s")

        validation_script = textwrap.dedent(
            """
            import hashlib
            import json
            import os
            import sys

            root = "node_modules"
            manifest_path = "node_modules_manifest.json"

            if not os.path.exists(manifest_path):
                print(json.dumps({"error": "manifest_missing"}))
                sys.exit(1)

            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)

            expected_entries = [tuple(entry) for entry in manifest.get("entries", [])]
            expected_set = set(expected_entries)

            current_entries = []
            file_count = 0
            dir_count = 0
            symlink_count = 0

            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                for name in dirnames + filenames:
                    full_path = os.path.join(dirpath, name)
                    rel_path = os.path.relpath(full_path, root)
                    if os.path.islink(full_path):
                        entry = ("L", rel_path, os.readlink(full_path))
                        symlink_count += 1
                    elif os.path.isdir(full_path):
                        entry = ("D", rel_path)
                        dir_count += 1
                    else:
                        entry = ("F", rel_path)
                        file_count += 1
                    current_entries.append(entry)

            current_entries.sort()
            current_set = set(current_entries)

            digest = hashlib.sha256()
            for entry in current_entries:
                digest.update("\0".join(map(str, entry)).encode())
            current_hash = digest.hexdigest()

            missing_set = expected_set - current_set
            extra_set = current_set - expected_set

            summary = {
                "expected_count": len(expected_set),
                "current_count": len(current_set),
                "expected_hash": manifest.get("hash"),
                "current_hash": current_hash,
                "missing_count": len(missing_set),
                "extra_count": len(extra_set),
                "missing_preview": sorted(missing_set, key=lambda x: x[1])[:20],
                "extra_preview": sorted(extra_set, key=lambda x: x[1])[:20],
                "expected_stats": manifest.get("stats"),
                "current_stats": {
                    "files": file_count,
                    "directories": dir_count,
                    "symlinks": symlink_count,
                },
            }

            print(json.dumps(summary))

            if missing_set or extra_set or (
                manifest.get("hash") and manifest["hash"] != current_hash
            ):
                sys.exit(1)
            """
        )

        validation_rc, validation_summary = run_python_json(
            resume_sb,
            validation_script,
            "13. Validating node_modules manifest after resume...",
        )

        if validation_rc != 0:
            print("   ERROR: Node_modules integrity mismatch detected after resume.")
    except Exception as e:
        snapshot_duration = time.time() - snapshot_start
        print(f"   FAILED: Snapshot or resume failed after {snapshot_duration:.2f}s")
        print(f"   Error: {str(e)}")
        print(f"   Error type: {type(e).__name__}")
        validation_summary = None
        validation_rc = -1
    finally:
        if resume_sb is not None:
            print("\n14. Terminating resumed sandbox...")
            resume_sb.terminate()
            print("    Resumed sandbox terminated")

    # Clean up
    if 'image' not in locals():
        print("\nCleanup: Terminating sandbox...")
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
    if 'image' in locals():
        print(f"Snapshot duration: {snapshot_duration:.2f}s")
    if manifest_summary:
        print(
            f"Manifest hash before suspend: {manifest_summary.get('hash', 'n/a')} "
            f"(entries: {manifest_summary.get('entry_count', 'n/a')})"
        )
        stats = manifest_summary.get("stats") or {}
        print(
            "Manifest stats before suspend: "
            f"files={stats.get('files', 'n/a')}, directories={stats.get('directories', 'n/a')}, "
            f"symlinks={stats.get('symlinks', 'n/a')}"
        )
    if 'validation_summary' in locals() and validation_summary:
        print(
            f"Post-resume hash: {validation_summary.get('current_hash', 'n/a')} "
            f"(missing: {validation_summary.get('missing_count', 'n/a')}, extra: {validation_summary.get('extra_count', 'n/a')})"
        )
        current_stats = validation_summary.get("current_stats") or {}
        print(
            "Manifest stats after resume: "
            f"files={current_stats.get('files', 'n/a')}, directories={current_stats.get('directories', 'n/a')}, "
            f"symlinks={current_stats.get('symlinks', 'n/a')}"
        )
        if validation_summary.get("missing_preview"):
            print("Sample missing entries:")
            for entry in validation_summary["missing_preview"][:5]:
                print(f"  - {entry}")
        if validation_summary.get("extra_preview"):
            print("Sample extra entries:")
            for entry in validation_summary["extra_preview"][:5]:
                print(f"  + {entry}")
    if 'validation_rc' in locals():
        print(f"Node_modules validation: {'PASS' if validation_rc == 0 else 'FAIL'}")
    print("=" * 60)

    if 'validation_rc' in locals() and validation_rc != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
