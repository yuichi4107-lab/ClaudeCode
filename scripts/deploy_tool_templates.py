"""
Deploy 9 tool templates to VPS and rebuild Docker container.
Usage: python scripts/deploy_tool_templates.py
"""
import paramiko
import os

HOST = '163.44.101.31'
USER = 'root'
PASSWORD = os.environ.get("VPS_ROOT_PW", "")  # 2026-05-30 ハードコード除去。環境変数で供給
BASE_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'yn-tools', 'app', 'templates', 'tools')
BASE_REMOTE = '/opt/yn-tools/app/templates/tools'

TOOLS = [
    'expense',
    'seocheck',
    'salesboard',
    'estimate',
    'passgen',
    'dailyreport',
    'cardreader',
    'voiceminutes',
    'sales',
]

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f'Connecting to {HOST}...')
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    sftp = ssh.open_sftp()
    print('Connected.')

    for slug in TOOLS:
        local_path = os.path.join(BASE_LOCAL, slug, 'index.html')
        remote_path = f'{BASE_REMOTE}/{slug}/index.html'

        if not os.path.exists(local_path):
            print(f'  SKIP {slug}: local file not found at {local_path}')
            continue

        with open(local_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Ensure remote directory exists
        try:
            sftp.stat(f'{BASE_REMOTE}/{slug}')
        except FileNotFoundError:
            print(f'  Creating directory {BASE_REMOTE}/{slug}')
            ssh.exec_command(f'mkdir -p {BASE_REMOTE}/{slug}')

        # Write file in binary mode with UTF-8 encoding
        with sftp.file(remote_path, 'wb') as remote_file:
            remote_file.write(content.encode('utf-8'))

        # Verify
        stat = sftp.stat(remote_path)
        print(f'  OK {slug}/index.html ({stat.st_size} bytes)')

    sftp.close()

    # Rebuild and deploy
    print('\nRebuilding Docker container...')
    cmd = 'cd /opt/yn-tools && docker compose build app && docker compose up -d'
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)

    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    exit_code = stdout.channel.recv_exit_status()

    if out:
        print(out)
    if err:
        print(err)

    if exit_code == 0:
        print('\nDeploy complete!')
    else:
        print(f'\nDeploy failed with exit code {exit_code}')

    ssh.close()

if __name__ == '__main__':
    main()
