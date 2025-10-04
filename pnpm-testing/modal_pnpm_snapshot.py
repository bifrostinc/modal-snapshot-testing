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

    manifest_script = textwrap.dedent(
        """
        set -euo pipefail

        root="node_modules"
        if [ ! -d "$root" ]; then
            echo '{"error": "node_modules_missing"}'
            exit 1
        fi

        manifest_txt="node_modules_manifest.txt"
        temp_manifest="${manifest_txt}.tmp"

        {
            find "$root" -mindepth 1 -type d -printf "D\\t%P\\n"
            find "$root" -type f -printf "F\\t%P\\n"
            find "$root" -type l -printf "L\\t%P\\t%l\\n"
        } | LC_ALL=C sort > "$temp_manifest"

        mv "$temp_manifest" "$manifest_txt"

        stats=$(awk -F '\\t' 'BEGIN {total=0; files=0; dirs=0; links=0}
            {total++}
            $1=="F"{files++}
            $1=="D"{dirs++}
            $1=="L"{links++}
            END {printf "%d %d %d %d", total, files, dirs, links}' "$manifest_txt")

        IFS=' ' read -r entry_count files directories symlinks <<< "$stats"

        hash=$(sha256sum "$manifest_txt" | awk '{print $1}')

        cat <<JSON > node_modules_manifest.json
{"manifest_path": "$manifest_txt", "hash": "$hash", "entry_count": $entry_count, "stats": {"files": $files, "directories": $directories, "symlinks": $symlinks}}
JSON

        cat node_modules_manifest.json
        """
    )

    manifest_rc, manifest_summary = run_script_json(
        sb,
        manifest_script,
        "9. Recording node_modules manifest before suspend...",
        interpreter="bash",
    )

    if manifest_rc != 0:
        print("   ERROR: Failed to record node_modules manifest.")

    # Check python availability to aid debugging when manifests fail to generate
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
            import hashlib
            import json
            import os
            import subprocess
            import sys

            meta_path = "node_modules_manifest.json"
            if not os.path.exists(meta_path):
                print(json.dumps({"error": "manifest_missing"}))
                sys.exit(1)

            with open(meta_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)

            expected_manifest_path = manifest.get("manifest_path", "node_modules_manifest.txt")
            if not os.path.exists(expected_manifest_path):
                print(
                    json.dumps(
                        {
                            "error": "manifest_file_missing",
                            "manifest_path": expected_manifest_path,
                        }
                    )
                )
                sys.exit(1)

            regen_script = '''
            set -euo pipefail
            root="node_modules"
            manifest_txt="node_modules_manifest_after.txt"
            temp_manifest="${manifest_txt}.tmp"
            {
                find \"$root\" -mindepth 1 -type d -printf \"D\\t%P\\n\"
                find \"$root\" -type f -printf \"F\\t%P\\n\"
                find \"$root\" -type l -printf \"L\\t%P\\t%l\\n\"
            } | LC_ALL=C sort > \"$temp_manifest\"
            mv \"$temp_manifest\" \"$manifest_txt\"
            '''

            result = subprocess.run(
                ["bash", "-lc", regen_script], capture_output=True, text=True
            )
            if result.returncode != 0:
                print(
                    json.dumps(
                        {
                            "error": "manifest_regen_failed",
                            "returncode": result.returncode,
                            "stdout": result.stdout.strip(),
                            "stderr": result.stderr.strip(),
                        }
                    )
                )
                sys.exit(result.returncode or 1)

            current_manifest_path = "node_modules_manifest_after.txt"

            expected_set: set[str] = set()
            with open(expected_manifest_path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    expected_set.add(raw.rstrip("\n"))

            current_set: set[str] = set()
            current_stats = {"files": 0, "directories": 0, "symlinks": 0}
            with open(current_manifest_path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.rstrip("\n")
                    current_set.add(line)
                    if not line:
                        continue
                    prefix = line.split("\t", 1)[0]
                    if prefix == "F":
                        current_stats["files"] += 1
                    elif prefix == "D":
                        current_stats["directories"] += 1
                    elif prefix == "L":
                        current_stats["symlinks"] += 1

            def sha256_file(path: str) -> str:
                digest = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        digest.update(chunk)
                return digest.hexdigest()

            missing = sorted(expected_set - current_set)[:20]
            extra = sorted(current_set - expected_set)[:20]

            summary = {
                "expected_count": len(expected_set),
                "current_count": len(current_set),
                "expected_hash": manifest.get("hash"),
                "current_hash": sha256_file(current_manifest_path),
                "missing_count": len(expected_set - current_set),
                "extra_count": len(current_set - expected_set),
                "missing_preview": missing,
                "extra_preview": extra,
                "expected_stats": manifest.get("stats"),
                "current_stats": current_stats,
            }

            print(json.dumps(summary))

            if (
                summary["missing_count"]
                or summary["extra_count"]
                or (manifest.get("hash") and manifest["hash"] != summary["current_hash"])
            ):
                sys.exit(1)
            """
        )

        validation_rc, validation_summary = run_script_json(
            resume_sb,
            validation_script,
            "14. Validating node_modules manifest after resume...",
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
