#!/usr/bin/env python3
"""Package MVPy research assets for Colab.

The Colab runtime should not depend on this whole dirty worktree. This script
creates a small reproducible bundle with only the data and scripts needed for
active-teacher generation, verifier runs, SFT prep, training, and OOD eval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PATHS = [
    "data/mvpy_research_mlx_raw_v2",
    "data/mvpy_research_mlx_plan_v2",
    "data/mvpy_research_v2_oodmix",
    "data/mvpy_ood_500",
    "data/mvpy_ood_holdout_v2",
    "scripts/eval_mvpy_predictions.py",
    "colab/mvpy_colab_plan.py",
    "colab/mvpy_active_teacher.py",
    "colab/train_unsloth_mvpy.py",
    "colab/README.md",
    "colab/MVPy_Active_Teacher_Colab.ipynb",
    "colab/colab_mcp_config.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(paths: list[str]):
    for rel in paths:
        path = ROOT / rel
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file():
            yield rel, path
        else:
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    yield child.relative_to(ROOT).as_posix(), child


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results/mvpy_colab/mvpy_colab_bundle.tar.gz",
    )
    parser.add_argument("--include", action="append", default=[])
    args = parser.parse_args()

    paths = DEFAULT_PATHS + args.include
    args.out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "paths": [],
    }

    with tarfile.open(args.out, "w:gz") as tar:
        for rel, path in iter_files(paths):
            arcname = f"mvpy_colab/{rel}"
            tar.add(path, arcname=arcname)
            manifest["paths"].append(
                {
                    "path": rel,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
        info = tarfile.TarInfo("mvpy_colab/manifest.json")
        data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        info.size = len(data)
        info.mtime = int(time.time())
        tar.addfile(info, fileobj=__import__("io").BytesIO(data))

    print(json.dumps({"out": str(args.out), "bytes": args.out.stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
