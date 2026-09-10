"""Assemble exact tracked source plus public pinned seeds and offline wheels."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True,
                          capture_output=True, timeout=120).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assemble() -> Path:
    stage = ROOT / "artifacts/autobenchmark"
    if stage.exists():
        raise FileExistsError("Release stage must be fresh")
    stage.mkdir(parents=True)
    head = git("rev-parse", "HEAD").decode().strip()
    files = git("ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
    for raw in files:
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe tracked path")
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git("show", f"{head}:{relative}"))
    wheels = ROOT / "vendor/wheels"
    if not list(wheels.glob("*.whl")):
        raise ValueError("Download pinned launcher wheels before packaging")
    wheel_manifest = {path.name: sha256(path) for path in sorted(wheels.glob("*.whl"))}
    (wheels / "SHA256SUMS.json").write_text(json.dumps(wheel_manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copytree(wheels, stage / "vendor/wheels")
    seeds = {}
    for manifest in sorted((stage / "corpus/projects").glob("*.json")):
        project = json.loads(manifest.read_text(encoding="utf-8"))
        name = project["project_id"] + ".bundle"
        source = ROOT / ".bench/seeds" / name
        if not source.is_file():
            raise ValueError(f"Missing seed: {name}")
        heads = git("bundle", "list-heads", str(source)).decode().splitlines()
        expected = project["source"]["commit_sha"] + " refs/heads/bench-seed"
        if expected not in heads:
            raise ValueError(f"Wrong pinned seed: {name}")
        destination = stage / ".bench/seeds" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        seeds[name] = {"sha256": sha256(source), "commit": project["source"]["commit_sha"],
                       "source_digest": project["source"]["source_tree_digest"]}
    tracked_and_payload = {path.relative_to(stage).as_posix(): sha256(path)
                           for path in sorted(stage.rglob("*")) if path.is_file()}
    metadata = {"schema": "autobench.release/v1", "source_commit": head,
                "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
                "files": tracked_and_payload, "seeds": seeds,
                "live_model_called": False, "coding_quality_measured": False}
    (stage / ".bench/release.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": str(stage), "source_commit": head,
                      "files": len(tracked_and_payload), "seeds": len(seeds)}))
    return stage


if __name__ == "__main__":
    assemble()
