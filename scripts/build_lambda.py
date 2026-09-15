"""Build a Linux/CPython-3.11 deployment bundle for AWS Lambda.

    python3 -m scripts.build_lambda

Produces ``galen_lambda.zip`` at the repo root containing the ASGI app, the
``agent`` package, the static ``ui`` and every third-party dependency built for
the Lambda runtime (manylinux wheels, so binary deps such as pydantic-core are
resolved without touching this Mac's environment).
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "lambda"
OUT = ROOT / "galen_lambda.zip"
TARGET_PYTHON = "3.11"

DEPS = ["fastapi", "mangum", "httpx", "assemblyai", "python-dotenv", "python-multipart"]
PACKAGES = ["app", "agent", "ui"]


def main() -> int:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--quiet", "--target", str(BUILD),
        "--platform", "manylinux2014_x86_64",
        "--implementation", "cp",
        "--python-version", TARGET_PYTHON,
        "--only-binary=:all:",
        "--upgrade", *DEPS,
    ])

    for pkg in PACKAGES:
        shutil.copytree(
            ROOT / pkg, BUILD / pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.db-*"),
        )

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BUILD.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(BUILD))

    print(f"built {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
