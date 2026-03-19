import json
import os
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FAQS_DIR = DATA_DIR / "faqs"
INSTRUCTIONS_DIR = DATA_DIR / "instructions"
PLATFORMS_CONFIG_PATH = PROJECT_ROOT / "app" / "rag" / "platforms.yaml"

CHUNK_SEPARATOR = "<<<CHUNK_SEPARATOR>>>"
BROWSER_CACHE_SPLIT_FILES = [
    "ia_browser_cache_clear_chrome.txt",
    "ia_browser_cache_clear_chrome_ipad.txt",
    "ia_browser_cache_clear_firefox.txt",
    "ia_browser_cache_clear_safari.txt",
]
LEGACY_BROWSER_CACHE_FILE = "ia_browser_cache_clear.txt"


def validate_index_file(filepath: Path, label: str) -> bool:
    if not filepath.exists():
        print(f"FAIL: Missing {label} index file: {filepath}")
        return False
    if filepath.stat().st_size == 0:
        print(f"FAIL: Empty {label} index file: {filepath}")
        return False
    print(f"PASS: {label} index found and not empty: {filepath}")
    return True


def load_platforms() -> list[dict]:
    try:
        with PLATFORMS_CONFIG_PATH.open("r", encoding="utf-8") as file_obj:
            platforms_config = yaml.safe_load(file_obj) or {}
    except FileNotFoundError:
        print(f"FAIL: platforms.yaml not found at {PLATFORMS_CONFIG_PATH}")
        sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"FAIL: Error parsing platforms.yaml at {PLATFORMS_CONFIG_PATH}: {exc}")
        sys.exit(1)
    return platforms_config.get("platforms", [])


def iter_chunk_metas(chunks_path: Path) -> list[dict]:
    if not chunks_path.exists():
        return []

    text = chunks_path.read_text(encoding="utf-8")
    chunks = [chunk.strip() for chunk in text.split(CHUNK_SEPARATOR) if chunk.strip()]
    metas: list[dict] = []

    for index, chunk in enumerate(chunks):
        first_line = chunk.splitlines()[0] if chunk.splitlines() else ""
        if not first_line.startswith("[META:") or not first_line.endswith("]"):
            raise ValueError(f"Missing [META:...] header in {chunks_path} chunk {index}")
        raw_meta = first_line[len("[META:"):-1]
        meta = json.loads(raw_meta)
        metas.append(meta)

    return metas


def validate_platform_chunk_file(platform_key: str, label: str) -> bool:
    chunks_path = INSTRUCTIONS_DIR / f"instructions_chunks_{platform_key}.txt"
    if not chunks_path.exists():
        print(f"FAIL: Missing {label} chunks file: {chunks_path}")
        return False

    try:
        metas = iter_chunk_metas(chunks_path)
    except Exception as exc:
        print(f"FAIL: Could not parse {label} chunks file {chunks_path}: {exc}")
        return False

    contaminated = []
    for meta in metas:
        platforms = meta.get("platform", [])
        if platform_key not in platforms or any(p != platform_key for p in platforms):
            contaminated.append(
                f"{meta.get('source_file', '<unknown>')} -> platform={platforms}"
            )

    if contaminated:
        print(f"FAIL: {label} chunks contain cross-platform contamination:")
        for item in contaminated:
            print(f"  - {item}")
        return False

    print(f"PASS: {label} chunks only contain platform '{platform_key}' metadata")
    return True


def validate_browser_cache_split_files() -> bool:
    ok = True

    for filename in BROWSER_CACHE_SPLIT_FILES:
        path = FAQS_DIR / filename
        if not path.exists():
            print(f"FAIL: Missing split browser cache FAQ file: {path}")
            ok = False
        else:
            print(f"PASS: Split browser cache FAQ file exists: {path}")

    faq_chunks_path = FAQS_DIR / "faqs_chunks.txt"
    try:
        metas = iter_chunk_metas(faq_chunks_path)
    except Exception as exc:
        print(f"FAIL: Could not parse FAQ chunks file {faq_chunks_path}: {exc}")
        return False

    source_files = {meta.get("source_file") for meta in metas}
    for filename in BROWSER_CACHE_SPLIT_FILES:
        if filename not in source_files:
            print(f"FAIL: Split browser cache file missing from FAQ index metadata: {filename}")
            ok = False
        else:
            print(f"PASS: Split browser cache file present in FAQ index metadata: {filename}")

    return ok


def validate_legacy_browser_cache_absent() -> bool:
    ok = True
    for directory in (FAQS_DIR, INSTRUCTIONS_DIR):
        legacy_path = directory / LEGACY_BROWSER_CACHE_FILE
        if legacy_path.exists():
            print(f"FAIL: Legacy browser cache file should not exist: {legacy_path}")
            ok = False
        else:
            print(f"PASS: Legacy browser cache file absent: {legacy_path}")
    return ok


def main() -> None:
    print("--- Validating FAISS Indexes ---")
    all_passed = True

    all_passed &= validate_index_file(FAQS_DIR / "faiss_index", "FAQ")
    all_passed &= validate_index_file(INSTRUCTIONS_DIR / "faiss_index", "General Instructions")

    platforms = load_platforms()
    if not platforms:
        print("WARNING: No platforms defined in platforms.yaml. Skipping platform-specific index validation.")

    for platform in platforms:
        platform_key = platform["key"]
        platform_label = platform.get("display_name", platform_key)
        platform_index_path = INSTRUCTIONS_DIR / f"faiss_index_{platform_key}"
        all_passed &= validate_index_file(platform_index_path, f"{platform_label} (Platform)")
        all_passed &= validate_platform_chunk_file(platform_key, f"{platform_label} (Platform)")

    all_passed &= validate_browser_cache_split_files()
    all_passed &= validate_legacy_browser_cache_absent()

    if all_passed:
        print("\n--- All FAISS indexes validated successfully! ---")
        sys.exit(0)

    print("\n--- FAISS index validation FAILED! ---")
    sys.exit(1)


if __name__ == "__main__":
    main()
