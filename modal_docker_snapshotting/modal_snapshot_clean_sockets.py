import modal

# Create a simple Ubuntu-based image
ubuntu_image = modal.Image.from_registry("ubuntu:22.04")


def main():
    print("Looking up modal.Sandbox app")
    app = modal.App.lookup("snapshot-clean-sockets-demo", create_if_missing=True)
    print("Creating sandbox")

    with modal.enable_output():
        # Create a sandbox that runs sleep infinity to keep it alive
        sb = modal.Sandbox.create(
            "sleep",
            "infinity",
            timeout=60 * 60,  # 1 hour timeout
            app=app,
            image=ubuntu_image,
        )

    print("Sandbox created and running")
    
    # Find all .sock files in the filesystem
    print("Finding all .sock files in the filesystem...")
    find_cmd = sb.exec("find", "/", "-name", "*.sock", "-type", "s", "2>/dev/null", "||", "true")
    sock_files = find_cmd.stdout.read().strip().split('\n')
    find_cmd.wait()
    
    # Filter out empty strings
    sock_files = [f for f in sock_files if f]
    
    print(f"Found {len(sock_files)} socket files")
    
    # Separate files into those to keep (containing "modal") and those to delete
    modal_socks = []
    socks_to_delete = []
    
    for sock_file in sock_files:
        if "modal" in sock_file.lower():
            modal_socks.append(sock_file)
        else:
            socks_to_delete.append(sock_file)
    
    print(f"Socket files containing 'modal' (will be kept): {len(modal_socks)}")
    for sock in modal_socks[:5]:  # Show first 5
        print(f"  - {sock}")
    if len(modal_socks) > 5:
        print(f"  ... and {len(modal_socks) - 5} more")
    
    print(f"\nSocket files to delete: {len(socks_to_delete)}")
    for sock in socks_to_delete[:5]:  # Show first 5
        print(f"  - {sock}")
    if len(socks_to_delete) > 5:
        print(f"  ... and {len(socks_to_delete) - 5} more")
    
    # Delete the socket files that don't contain "modal"
    if socks_to_delete:
        print("\nDeleting socket files...")
        for sock_file in socks_to_delete:
            # Use rm -f to force removal and avoid errors if file doesn't exist
            p = sb.exec("rm", "-f", sock_file)
            p.wait()
        print(f"Deleted {len(socks_to_delete)} socket files")
    else:
        print("\nNo socket files to delete")
    
    # Verify deletion by checking again
    print("\nVerifying deletion...")
    verify_cmd = sb.exec("find", "/", "-name", "*.sock", "-type", "s", "2>/dev/null", "||", "true")
    remaining_socks = verify_cmd.stdout.read().strip().split('\n')
    verify_cmd.wait()
    remaining_socks = [f for f in remaining_socks if f]
    
    print(f"Remaining socket files: {len(remaining_socks)}")
    for sock in remaining_socks[:10]:  # Show first 10
        print(f"  - {sock}")
    if len(remaining_socks) > 10:
        print(f"  ... and {len(remaining_socks) - 10} more")
    
    # Create some test files to show other changes
    print("\nCreating test files for demonstration...")
    sb.exec("mkdir", "-p", "/cleaned_test").wait()
    sb.exec("echo", "Snapshot after cleaning sockets", stdout=sb.open("/cleaned_test/info.txt", "w")).wait()
    
    print("\nCreating snapshot...")
    image = sb.snapshot_filesystem()
    print("Snapshot created successfully!")
    print(f"Snapshot image: {image}")
    
    # Terminate the sandbox
    sb.terminate()
    print("Sandbox terminated")
    
    # The snapshot now contains a filesystem with all non-modal .sock files removed
    # This can be useful for creating cleaner base images


if __name__ == "__main__":
    main()