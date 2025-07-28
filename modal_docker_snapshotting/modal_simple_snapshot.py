import modal

# Create a simple Ubuntu-based image
ubuntu_image = modal.Image.from_registry("ubuntu:22.04")


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
            image=ubuntu_image,
        )

    print("Sandbox created and running")
    
    # You can execute commands in the running sandbox
    print("Testing sandbox with a simple command")
    p = sb.exec("echo", "Hello from the sandbox!")
    output = p.stdout.read()
    print(f"Output: {output}")
    p.wait()
    
    # Install some packages to demonstrate state changes
    print("Installing some packages...")
    p = sb.exec("apt-get", "update")
    p.wait()
    
    p = sb.exec("apt-get", "install", "-y", "curl", "wget", "htop")
    p.wait()
    print("Packages installed")
    
    # Create some files to demonstrate filesystem changes
    print("Creating test files...")
    sb.exec("mkdir", "-p", "/test_directory").wait()
    sb.exec("echo", "This is a test file", stdout=sb.open("/test_directory/test.txt", "w")).wait()
    
    # Verify the file was created
    p = sb.exec("cat", "/test_directory/test.txt")
    print(f"File contents: {p.stdout.read()}")
    p.wait()
    
    print("Creating snapshot...")
    image = sb.snapshot_filesystem()
    print("Snapshot created successfully!")
    print(f"Snapshot image: {image}")
    
    # Terminate the sandbox
    sb.terminate()
    print("Sandbox terminated")
    
    # Now you could use this snapshot as a base image for other Modal functions
    # For example:
    # @modal.function(image=image)
    # def my_function():
    #     # This function will have all the packages and files from the snapshot
    #     pass


if __name__ == "__main__":
    main()