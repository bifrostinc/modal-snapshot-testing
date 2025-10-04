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

    # Helper utilities for snapshot generation and validation
    def run_script_json(sb_handle, script, step_description, *, interpreter="python3"):
        print(f"\n{step_description}")
        if interpreter == "python3":
            command = "cd /workspace/slidev && python3 - <<'PY'\n" + script + "\nPY\n"
        elif interpreter == "bash":
            command = "cd /workspace/slidev && bash <<'BASH'\n" + script + "\nBASH\n"
        else:
            command = (
                "cd /workspace/slidev && "
                + interpreter
                + " <<'MODALSCRIPT'\n"
                + script
                + "\nMODALSCRIPT\n"
            )
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

    snapshot_script = textwrap.dedent(
        """
        import json
        import os
        import subprocess
        import sys

        root = "node_modules"
        if not os.path.isdir(root):
            print(json.dumps({"error": "node_modules_missing"}))
            sys.exit(1)

        def run(cmd: str) -> str:
            result = subprocess.run(["bash", "-lc", cmd], text=True, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(f"Command failed ({cmd}): {result.stderr.strip()}")
            return result.stdout

        def capture_count(cmd: str) -> int:
            output = run(cmd).strip()
            if not output:
                return 0
            return int(output.split()[0])

        def capture_lines(cmd: str, limit: int | None = None) -> list[str]:
            lines = [line.strip() for line in run(cmd).splitlines() if line.strip()]
            if limit is not None:
                return lines[:limit]
            return lines

        data = {
            "package_json_count": capture_count(
                "find node_modules -name package.json -type f | wc -l"
            ),
            "top_entries": capture_lines(
                "find node_modules -maxdepth 1 -mindepth 1 -printf '%f\\n' | LC_ALL=C sort | head -n 25"
            ),
            "sample_packages": capture_lines(
                "find node_modules -maxdepth 2 -name package.json -type f | LC_ALL=C sort | head -n 100"
            ),
            "top_entry_count": len([name for name in os.listdir(root)]),
        }

        pnpm_dir = os.path.join(root, ".pnpm")
        if os.path.isdir(pnpm_dir):
            data["pnpm_entries"] = capture_lines(
                "find node_modules/.pnpm -maxdepth 1 -mindepth 1 -printf '%f\\n' | LC_ALL=C sort | head -n 25"
            )
            data["pnpm_entry_count"] = len([name for name in os.listdir(pnpm_dir)])
        else:
            data["pnpm_entries"] = []
            data["pnpm_entry_count"] = 0

        with open("node_modules_snapshot.json", "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        print(
            json.dumps(
                {
                    "package_json_count": data["package_json_count"],
                    "top_entries_sample": data["top_entries"][:5],
                    "pnpm_entries_sample": data["pnpm_entries"][:5],
                    "sample_package_paths": data["sample_packages"][:5],
                }
            )
        )
        """
    )

    snapshot_rc, snapshot_summary = run_script_json(
        sb,
        snapshot_script,
        "9. Recording node_modules snapshot before suspend...",
    )

    if snapshot_rc != 0:
        print("   ERROR: Failed to record node_modules snapshot.")
    snapshot_data_json = json.dumps(snapshot_summary or {})

    # Check python availability to aid debugging when snapshot capture fails
    print("\n10. Checking python3 availability inside sandbox...")
    p = sb.exec("python3", "--version")
    python_version = p.stdout.read().strip()
    p.wait()
    if python_version:
        print(f"   python3 reports: {python_version}")
    if p.returncode != 0:
        print(f"   WARNING: python3 --version returned {p.returncode}")

    # Attempt to create a snapshot
    print("\n11. Attempting to create filesystem snapshot (simulated suspend)...")
    snapshot_start = time.time()

    resume_sb = None
    try:
        image = sb.snapshot_filesystem()
        snapshot_duration = time.time() - snapshot_start
        print(f"   SUCCESS: Snapshot created in {snapshot_duration:.2f}s")
        print(f"   Snapshot image: {image}")

        print("\n12. Terminating original sandbox before resume...")
        sb.terminate()
        print("    Original sandbox terminated")

        print("\n13. Creating resumed sandbox from snapshot image...")
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
            import json
            import os
            import sys

            snapshot = json.loads('''__SNAPSHOT_DATA__''')

            root = "node_modules"
            if not os.path.isdir(root):
                print(json.dumps({"error": "node_modules_missing_post_resume"}))
                sys.exit(1)

            tracked_top_entries = snapshot.get("top_entries_sample", [])
            tracked_pnpm_entries = snapshot.get("pnpm_entries_sample", [])
            tracked_sample_packages = snapshot.get("sample_package_paths", [])

            current_top_entry_count = len([name for name in os.listdir(root)])
            pnpm_dir = os.path.join(root, ".pnpm")
            current_pnpm_entry_count = (
                len([name for name in os.listdir(pnpm_dir)])
                if os.path.isdir(pnpm_dir)
                else 0
            )

            missing_top_entries = [
                entry
                for entry in tracked_top_entries
                if not os.path.exists(os.path.join(root, entry))
            ]
            missing_pnpm_entries = [
                entry
                for entry in tracked_pnpm_entries
                if not os.path.exists(os.path.join(root, ".pnpm", entry))
            ]
            missing_sample_packages = [
                path
                for path in tracked_sample_packages
                if not os.path.exists(path)
            ]

            summary = {
                "expected_package_json_count": snapshot.get("package_json_count"),
                "tracked_top_entries": len(tracked_top_entries),
                "tracked_pnpm_entries": len(tracked_pnpm_entries),
                "tracked_sample_packages": len(tracked_sample_packages),
                "missing_top_entries": missing_top_entries,
                "missing_pnpm_entries": missing_pnpm_entries,
                "missing_sample_packages": missing_sample_packages,
                "present_top_entries": len(tracked_top_entries) - len(missing_top_entries),
                "present_pnpm_entries": len(tracked_pnpm_entries) - len(missing_pnpm_entries),
                "present_sample_packages": len(tracked_sample_packages)
                - len(missing_sample_packages),
                "expected_top_entry_count": snapshot.get("top_entry_count"),
                "current_top_entry_count": current_top_entry_count,
                "expected_pnpm_entry_count": snapshot.get("pnpm_entry_count"),
                "current_pnpm_entry_count": current_pnpm_entry_count,
            }

            print(json.dumps(summary))

            if (
                missing_top_entries
                or missing_pnpm_entries
                or missing_sample_packages
                or summary["expected_top_entry_count"] != summary["current_top_entry_count"]
                or summary["expected_pnpm_entry_count"] != summary["current_pnpm_entry_count"]
            ):
                sys.exit(1)
            """
        )
        validation_script = validation_script.replace("__SNAPSHOT_DATA__", snapshot_data_json)

        validation_rc, validation_summary = run_script_json(
            resume_sb,
            validation_script,
            "14. Validating node_modules snapshot after resume...",
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
            print("\n15. Terminating resumed sandbox...")
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
    if snapshot_summary:
        print(
            "Package.json count before suspend: "
            f"{snapshot_summary.get('package_json_count', 'n/a')}"
        )
        top_sample = snapshot_summary.get("top_entries_sample") or []
        if top_sample:
            print(
                "Top-level entries sample before suspend: "
                + ", ".join(top_sample[:5])
            )
    if 'validation_summary' in locals() and validation_summary:
        print(
            "Tracked top entries present after resume: "
            f"{validation_summary.get('present_top_entries', 'n/a')} / "
            f"{validation_summary.get('tracked_top_entries', 'n/a')}"
        )
        print(
            "Tracked .pnpm entries present after resume: "
            f"{validation_summary.get('present_pnpm_entries', 'n/a')} / "
            f"{validation_summary.get('tracked_pnpm_entries', 'n/a')}"
        )
        print(
            "Tracked package.json samples present after resume: "
            f"{validation_summary.get('present_sample_packages', 'n/a')} / "
            f"{validation_summary.get('tracked_sample_packages', 'n/a')}"
        )
        print(
            "Top-level entry count after resume: "
            f"{validation_summary.get('current_top_entry_count', 'n/a')} "
            f"(expected {validation_summary.get('expected_top_entry_count', 'n/a')})"
        )
        print(
            ".pnpm entry count after resume: "
            f"{validation_summary.get('current_pnpm_entry_count', 'n/a')} "
            f"(expected {validation_summary.get('expected_pnpm_entry_count', 'n/a')})"
        )
        if validation_summary.get("missing_top_entries"):
            print("Missing top-level entries:")
            for entry in validation_summary["missing_top_entries"][:5]:
                print(f"  - {entry}")
        if validation_summary.get("missing_pnpm_entries"):
            print("Missing .pnpm entries:")
            for entry in validation_summary["missing_pnpm_entries"][:5]:
                print(f"  - {entry}")
        if validation_summary.get("missing_sample_packages"):
            print("Missing sampled package.json files:")
            for entry in validation_summary["missing_sample_packages"][:5]:
                print(f"  - {entry}")
    if 'validation_rc' in locals():
        print(f"Node_modules validation: {'PASS' if validation_rc == 0 else 'FAIL'}")
    print("=" * 60)

    if 'validation_rc' in locals() and validation_rc != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
