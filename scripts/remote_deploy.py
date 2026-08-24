import os
import sys
import tarfile
import tempfile
import paramiko
from pathlib import Path

HOST = "217.160.170.209"
USER = "root"
PASSWORD = sys.argv[1] if len(sys.argv) > 1 else ""

if not PASSWORD:
    print("Error: Password argument required")
    sys.exit(1)

print(f"[*] Connecting to {HOST} as {USER}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=15)
    print("[+] SSH connection established successfully!")
except Exception as e:
    print(f"[-] SSH connection failed: {e}")
    sys.exit(1)

# Step 1: Set up SSH Key for passwordless future access
print("[*] Setting up local SSH key for future passwordless deploys...")
ssh_dir = Path.home() / ".ssh"
ssh_dir.mkdir(parents=True, exist_ok=True)
key_path = ssh_dir / "id_ed25519"
pub_key_path = ssh_dir / "id_ed25519.pub"

if not key_path.exists():
    os.system(f'ssh-keygen -t ed25519 -N "" -f "{key_path}"')

if pub_key_path.exists():
    with open(pub_key_path, "r") as f:
        pub_key = f.read().strip()
    stdin, stdout, stderr = ssh.exec_command(f'mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "{pub_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys')
    stdout.channel.recv_exit_status()
    print("[+] Authorized keys updated on server.")

# Step 2: Package local project directory
print("[*] Packaging project files into tarball...")
tar_tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
tar_tmp.close()

root_dir = Path(__file__).resolve().parent.parent

def filter_files(tarinfo):
    name = tarinfo.name
    if any(ignore in name for ignore in [".venv", "__pycache__", ".git", ".DS_Store", ".pytest_cache", ".sqlite3", ".png"]):
        return None
    return tarinfo

with tarfile.open(tar_tmp.name, "w:gz") as tar:
    for item in root_dir.iterdir():
        if item.name not in [".venv", ".git", "__pycache__", ".pytest_cache", ".DS_Store"] and not item.name.endswith(".png"):
            tar.add(item, arcname=item.name, filter=filter_files)

print(f"[+] Archive created ({os.path.getsize(tar_tmp.name)} bytes). Uploading via SFTP...")

# Step 3: SFTP Upload
sftp = ssh.open_sftp()
remote_dest_dir = "/opt/synapse-mesh"
stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dest_dir}")
stdout.channel.recv_exit_status()

remote_tar = "/tmp/synapse_deploy.tar.gz"
sftp.put(tar_tmp.name, remote_tar)
sftp.close()
os.unlink(tar_tmp.name)
print("[+] Project archive uploaded.")

# Step 4: Extract and Deploy
print("[*] Extracting and running deploy.sh on server...")
cmd = f"cd {remote_dest_dir} && tar -xzf {remote_tar} && chmod +x deploy.sh && ./deploy.sh"
stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)

for line in iter(stdout.readline, ""):
    print(line, end="")

exit_code = stdout.channel.recv_exit_status()
print(f"[*] Remote deploy finished with exit code: {exit_code}")

if exit_code == 0:
    print("\n[+] Testing live endpoints...")
    stdin, stdout, stderr = ssh.exec_command("docker ps && curl -s http://localhost:8000/health")
    print(stdout.read().decode())
    print("\n[🚀] SYNAPSE-MESH IS LIVE!")
else:
    print(f"[-] Deployment encountered issues (code {exit_code})")
    print(stderr.read().decode())

ssh.close()
