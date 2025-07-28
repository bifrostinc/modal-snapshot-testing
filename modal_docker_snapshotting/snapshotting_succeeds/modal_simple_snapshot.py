import modal

base_image = modal.Image.from_registry("ubuntu:22.04", add_python="3.11")


def main():
    print("Looking up modal.Sandbox app")
    app = modal.App.lookup("simple-snapshot-demo", create_if_missing=True)
    print("Creating sandbox")

    with modal.enable_output():
        # Create a sandbox that runs sleep infinity to keep it alive
        sb = modal.Sandbox.create(
            "sleep",
            "infinity",
            timeout=60 * 60,  # 1 hour timeout
            app=app,
            image=base_image,
        )

    print("Sandbox created and running")
    
    print("Creating snapshot...")
    image = sb.snapshot_filesystem()
    print("Snapshot created successfully!")
    print(f"Snapshot image: {image}")
    
    # Terminate the sandbox
    sb.terminate()
    # print("Sandbox terminated")
    
if __name__ == "__main__":
    main()
