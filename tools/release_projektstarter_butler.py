#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BUTLER_METADATA_PATH = (
    ROOT_DIR / "plugin_sources" / "projektstarter_attribution_buttler" / "metadata.txt"
)
MASTER_METADATA_PATH = ROOT_DIR / "trassify_master_tools" / "metadata.txt"
PREPARE_SCRIPT_PATH = ROOT_DIR / "prepare_plugin_repository.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronisiert die Version von Projektstarter Butler und dem "
            "veroeffentlichten Master-Bundle und erzeugt die Repository-Artefakte neu."
        )
    )
    parser.add_argument(
        "--from-ref",
        help=(
            "Git-Referenz fuer die Erkennung, ob die metadata.txt bereits im Push "
            "angepasst wurde."
        ),
    )
    parser.add_argument(
        "--version",
        help="Zielversion im Format X.Y.Z. Ohne Angabe wird die Patch-Version erhoeht.",
    )
    return parser.parse_args()


def read_metadata_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} fehlt in {path}")


def write_metadata_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    replaced = False

    for line in lines:
        if line.startswith(f"{key}="):
            updated_lines.append(f"{key}={value}")
            replaced = True
            continue
        updated_lines.append(line)

    if not replaced:
        raise SystemExit(f"{key} fehlt in {path}")

    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def parse_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise SystemExit(f"Ungueltige Version: {version}. Erwartet wird X.Y.Z.")
    return tuple(int(part) for part in parts)


def bump_patch(version: str) -> str:
    major, minor, patch = parse_version(version)
    return f"{major}.{minor}.{patch + 1}"


def version_key(version: str) -> tuple[int, int, int]:
    return parse_version(version)


def git_changed_files(from_ref: str | None) -> set[str]:
    if not from_ref or set(from_ref) == {"0"}:
        return set()

    ref_check = subprocess.run(
        ["git", "rev-parse", "--verify", from_ref],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )
    if ref_check.returncode != 0:
        return set()

    diff_result = subprocess.run(
        ["git", "diff", "--name-only", from_ref, "HEAD"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in diff_result.stdout.splitlines() if line.strip()}


def choose_target_version(
    explicit_version: str | None,
    from_ref: str | None,
    butler_version: str,
    master_version: str,
) -> str:
    if explicit_version:
        parse_version(explicit_version)
        return explicit_version

    changed_files = git_changed_files(from_ref)
    butler_metadata_rel = str(BUTLER_METADATA_PATH.relative_to(ROOT_DIR))
    master_metadata_rel = str(MASTER_METADATA_PATH.relative_to(ROOT_DIR))

    if butler_metadata_rel in changed_files:
        return butler_version
    if master_metadata_rel in changed_files:
        return master_version

    base_version = max((butler_version, master_version), key=version_key)
    return bump_patch(base_version)


def main() -> int:
    args = parse_args()
    butler_version = read_metadata_value(BUTLER_METADATA_PATH, "version")
    master_version = read_metadata_value(MASTER_METADATA_PATH, "version")
    target_version = choose_target_version(
        explicit_version=args.version,
        from_ref=args.from_ref,
        butler_version=butler_version,
        master_version=master_version,
    )

    write_metadata_value(BUTLER_METADATA_PATH, "version", target_version)
    write_metadata_value(MASTER_METADATA_PATH, "version", target_version)

    subprocess.run([str(PREPARE_SCRIPT_PATH)], cwd=ROOT_DIR, check=True)

    print(
        "Version synchronisiert:",
        f"Projektstarter Butler={target_version},",
        f"Trassify Master Tools={target_version}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
