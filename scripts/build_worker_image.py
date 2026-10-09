"""Build a Worker image from only the SDK wheel and locked public dependencies."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="llm4om-worker:0.3.0")
    parser.add_argument("--offline", action="store_true", help="Resolve SDK build dependencies from the uv cache")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="llm4om-image-") as directory:
            context = Path(directory)
            wheels = context / "wheels"
            wheels.mkdir()
            subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheels),
                            *(["--offline"] if args.offline else [])], cwd=ROOT, check=True)
            subprocess.run(["uv", "export", "--locked", "--extra", "solve", "--no-dev", "--no-emit-project", "--no-header",
                            "--output-file", str(context / "runtime-requirements.txt"),
                            *(["--offline"] if args.offline else [])], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            shutil.copyfile(ROOT / "docker/worker.Dockerfile", context / "Dockerfile")
            subprocess.run(["docker", "build", "--pull=false", "--tag", args.tag, str(context)], check=True)
        return 0
    except (OSError, subprocess.SubprocessError):
        print("Worker image build failed; no source directory or secrets were used as Docker context.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
