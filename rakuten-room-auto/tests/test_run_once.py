from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_run_once_stops_after_failed_read_only_preflight(tmp_path):
    workspace_root = Path(__file__).resolve().parents[2]
    script = workspace_root / "rakuten-room-auto" / "scripts" / "run_once.sh"
    runtime_root = tmp_path / "runtime"
    venv_root = tmp_path / "venv"
    fake_bin = tmp_path / "bin"
    invocations = tmp_path / "python-invocations.log"
    (venv_root / "bin").mkdir(parents=True)
    fake_bin.mkdir()

    fake_python = venv_root / "bin" / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$RUN_ONCE_INVOCATIONS"\n'
        'if [[ "$*" == *" preview --limit 1"* ]]; then\n'
        "  exit 7\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    fake_lsof = fake_bin / "lsof"
    fake_lsof.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_lsof.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "RAKUTEN_ROOM_REPO_ROOT": str(workspace_root),
            "RAKUTEN_ROOM_RUNTIME_ROOT": str(runtime_root),
            "RAKUTEN_ROOM_VENV": str(venv_root),
            "RUN_ONCE_INVOCATIONS": str(invocations),
        }
    )
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 7
    assert invocations.read_text(encoding="utf-8").splitlines() == [
        "-m rakuten_room_auto preview --limit 1"
    ]
