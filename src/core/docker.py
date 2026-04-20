import subprocess


def run_in_docker(command: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "mydevteam-sandbox", "sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return (result.stdout + result.stderr).strip()
