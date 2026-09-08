#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
HOST_EVIDENCE="${1:-$ROOT/artifacts/harbor-phase2/windows-host/host.json}"
ARTIFACT_ROOT="$ROOT/artifacts/harbor-phase2/windows-host"
TRIALS_DIR="$ARTIFACT_ROOT/trials"
mkdir -p "$ARTIFACT_ROOT"

fail() {
  printf 'WINDOWS_HOST_QUALIFICATION_FAIL: %s\n' "$*" >&2
  exit 2
}

command -v git >/dev/null 2>&1 || fail "git is missing inside WSL"
command -v docker >/dev/null 2>&1 || fail "docker CLI is missing inside WSL"

PYTHON=""
for candidate in python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
[[ -n "$PYTHON" ]] || fail "Python >=3.12 is unavailable inside WSL after bootstrap"

DOCKER_OS="$(docker info --format '{{.OSType}}' 2>/dev/null || true)"
[[ "$DOCKER_OS" == "linux" ]] || fail "Docker daemon inside WSL must report OSType=linux; observed '$DOCKER_OS'"
LINUX_IDENTITY="$(docker run --rm --pull=missing alpine:3.20 uname -sm)"
[[ "$LINUX_IDENTITY" == Linux* ]] || fail "Docker Desktop did not execute a Linux container: '$LINUX_IDENTITY'"

readarray -t HARBOR_PIN < <("$PYTHON" - <<'PY'
import json
from pathlib import Path
lock = json.loads(Path('HARBOR.lock.json').read_text(encoding='utf-8'))
print(lock['version'])
print(lock['commit'])
PY
)
HARBOR_VERSION="${HARBOR_PIN[0]}"
HARBOR_COMMIT="${HARBOR_PIN[1]}"
CACHE_ROOT="$HOME/.cache/autonomous-dev-bench/harbor-$HARBOR_COMMIT"
HARBOR_SRC="$CACHE_ROOT/source"
VENV="$CACHE_ROOT/venv"
mkdir -p "$CACHE_ROOT"

if [[ ! -d "$HARBOR_SRC/.git" ]]; then
  rm -rf "$HARBOR_SRC"
  git init "$HARBOR_SRC"
  git -C "$HARBOR_SRC" remote add origin https://github.com/harbor-framework/harbor.git
fi
if [[ "$(git -C "$HARBOR_SRC" rev-parse HEAD 2>/dev/null || true)" != "$HARBOR_COMMIT" ]]; then
  git -C "$HARBOR_SRC" fetch --depth=1 origin "$HARBOR_COMMIT"
  git -C "$HARBOR_SRC" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$HARBOR_SRC" rev-parse HEAD)" == "$HARBOR_COMMIT" ]] || fail "Harbor source commit mismatch"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV" || fail "Python venv support is unavailable after bootstrap"
fi
"$VENV/bin/python" -m pip install --disable-pip-version-check -q --upgrade pip
"$VENV/bin/python" -m pip install --disable-pip-version-check -q 'pytest>=8' 'pytest-cov>=5' 'build>=1.2'
"$VENV/bin/python" -m pip install --disable-pip-version-check -q -e "$HARBOR_SRC"

OBSERVED_HARBOR="$("$VENV/bin/python" -c 'import importlib.metadata; print(importlib.metadata.version("harbor"))')"
[[ "$OBSERVED_HARBOR" == "$HARBOR_VERSION" ]] || fail "Harbor version mismatch: expected $HARBOR_VERSION observed $OBSERVED_HARBOR"

export PYTHONPATH="$ROOT:$ROOT/packages/benchmark_core${PYTHONPATH:+:$PYTHONPATH}"

rm -rf "$TRIALS_DIR"
"$VENV/bin/harbor" trials start \
  -p tests/harbor_phase2 \
  --agent suites.coding.harbor.probe_agent:HarborSubstrateProbeAgent \
  --trial-name phase2-windows-host \
  --trials-dir "$TRIALS_DIR"

"$VENV/bin/python" tools/verify_harbor_phase2_substrate.py --trials-dir "$TRIALS_DIR"

"$VENV/bin/python" - "$HOST_EVIDENCE" "$TRIALS_DIR" "$ARTIFACT_ROOT/PHASE2_WINDOWS_HOST.json" "$LINUX_IDENTITY" <<'PY'
import hashlib
import json
import platform
import sys
from pathlib import Path

host_path = Path(sys.argv[1])
trials_dir = Path(sys.argv[2])
out_path = Path(sys.argv[3])
linux_identity = sys.argv[4]
root = Path.cwd()
lock = json.loads((root / 'HARBOR.lock.json').read_text(encoding='utf-8'))
host = json.loads(host_path.read_text(encoding='utf-8'))

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    files = sorted(p for p in path.rglob('*') if p.is_file())
    if not files:
        raise SystemExit('Harbor trial produced no evidence files')
    for file in files:
        rel = file.relative_to(path).as_posix().encode()
        h.update(len(rel).to_bytes(8, 'big'))
        h.update(rel)
        data = file.read_bytes()
        h.update(len(data).to_bytes(8, 'big'))
        h.update(data)
    return h.hexdigest()

report = {
    'schema_version': 2,
    'scope': 'PHASE2_WINDOWS_PHYSICAL_HOST_HARBOR_DOCKER_QUALIFICATION',
    'status': 'PASS',
    'physical_host_os': 'windows',
    'bootstrap_mode': host.get('bootstrap_mode'),
    'controller_boundary': 'powershell_to_wsl2',
    'execution_backend': 'docker_desktop_linux_engine',
    'task_environment_os': 'linux_container',
    'native_windows_harbor_claimed': False,
    'official_swebench_semantics_preserved': True,
    'harbor': {
        'version': lock['version'],
        'commit': lock['commit'],
    },
    'wsl': {
        'distro': host.get('wsl', {}).get('distro'),
        'python': platform.python_version(),
        'kernel': platform.release(),
    },
    'container_identity': linux_identity,
    'model_called': False,
    'host_evidence_sha256': sha256_file(host_path),
    'trial_tree_sha256': tree_digest(trials_dir),
}
out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(out_path.read_text(encoding='utf-8'))
PY

printf '\nWINDOWS_HOST_QUALIFICATION_PASS\nEvidence: %s\n' "$ARTIFACT_ROOT/PHASE2_WINDOWS_HOST.json"
