"""Build a Worker image from only the SDK wheel and locked public dependencies."""

import argparse
import shutil
import subprocess
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from llm4om.executors import DEFAULT_IMAGE

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=DEFAULT_IMAGE)
    parser.add_argument("--offline", action="store_true", help="Resolve SDK build dependencies from the uv cache")
    parser.add_argument("--plugin-wheel", type=Path, action="append", default=[], help="Include an explicitly trusted plugin wheel in the immutable image")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="llm4om-image-") as directory:
            context = Path(directory)
            wheels = context / "wheels"
            wheels.mkdir()
            subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheels),
                            *(["--offline"] if args.offline else [])], cwd=ROOT, check=True)
            for path in args.plugin_wheel:
                with zipfile.ZipFile(path) as wheel:
                    metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
                    if len(metadata) != 1 or BytesParser().parsebytes(wheel.read(metadata[0]))["Name"] == "llm4om" or (wheels / path.name).exists():
                        raise ValueError("Plugin wheel cannot replace the SDK or another image wheel.")
                if path.suffix != ".whl":
                    raise ValueError("Expected a trusted built wheel.")
                shutil.copyfile(path, wheels / path.name)
            subprocess.run(["uv", "export", "--locked", "--extra", "solve", "--extra", "gurobi", "--extra", "ortools", "--no-dev", "--no-emit-project", "--no-header",
                            "--output-file", str(context / "runtime-requirements.txt"),
                            *(["--offline"] if args.offline else [])], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
            shutil.copyfile(ROOT / "docker/worker.Dockerfile", context / "Dockerfile")
            subprocess.run(["docker", "build", "--pull=false", "--tag", args.tag, str(context)], check=True)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError):
        print("Worker image build failed; no source directory or secrets were used as Docker context.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
