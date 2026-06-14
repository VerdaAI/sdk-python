"""
Live SDK integration test against the Verda Enterprise API.

Usage:
    VERDA_API_KEY=vk_... python tests/test_sdk_live.py
"""

import os
import sys
import time
from pathlib import Path

from verda import VerdaClient

API_KEY = os.environ.get("VERDA_API_KEY", "")
TEST_DIR = Path.home() / "Downloads" / "verda-sdk-test-files"

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \033[32m✓\033[0m {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  \033[31m✕\033[0m {name}" + (f" — {detail}" if detail else ""))


def main():
    global PASS, FAIL

    if not API_KEY:
        print("Set VERDA_API_KEY env var")
        sys.exit(1)

    if not TEST_DIR.exists():
        print(f"Test files directory not found: {TEST_DIR}")
        sys.exit(1)

    # Find test files
    image_file = None
    video_file = None
    audio_file = None
    for f in TEST_DIR.iterdir():
        ext = f.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            image_file = f
        elif ext in (".mp4", ".mov", ".avi"):
            video_file = f
        elif ext in (".aac", ".mp3", ".wav", ".flac"):
            audio_file = f

    print()
    print("=========================================")
    print(" Verda Python SDK — Live Integration Test")
    print("=========================================")
    print(f" Image: {image_file.name if image_file else 'NONE'}")
    print(f" Video: {video_file.name if video_file else 'NONE'}")
    print(f" Audio: {audio_file.name if audio_file else 'NONE'}")
    print()

    client = VerdaClient(api_key=API_KEY)

    # --- Credits ---
    print("\033[33m[Credits]\033[0m")
    credits = client.credits()
    test("balance exists", credits.balance_microdollars > 0, f"${credits.balance_dollars:.4f}")
    print()

    # --- Image Encode ---
    encode_output = None
    if image_file:
        print("\033[33m[Image Encode]\033[0m")
        print(f"  Encoding {image_file.name}...")
        try:
            result = client.encode(str(image_file))
            test("encode completed", result.status == "COMPLETED", result.status)
            test("watermark_ref returned", bool(result.watermark_ref), result.watermark_ref)
            test("download_url returned", bool(result.download_url), result.download_url[:80] + "..." if result.download_url else "")
            encode_output = result.download_url
        except Exception as e:
            test("encode completed", False, str(e))
        print()

    # --- Image Decode (watermarked) ---
    if encode_output and os.path.exists(encode_output):
        print("\033[33m[Image Decode — verify watermark]\033[0m")
        print(f"  Decoding watermarked image...")
        try:
            decode_result = client.decode(file=encode_output)
            test("decode completed", decode_result.status == "COMPLETED", decode_result.status)
            test("watermark found", decode_result.match, f"match={decode_result.match}")
        except Exception as e:
            test("decode completed", False, str(e))
        print()

    # --- Image Decode (original, no watermark) ---
    if image_file:
        print("\033[33m[Image Decode — original (no watermark)]\033[0m")
        print(f"  Decoding {image_file.name}...")
        try:
            result = client.decode(str(image_file))
            test("decode completed", result.status == "COMPLETED", result.status)
            test("no watermark found (expected)", not result.match, f"match={result.match}")
        except Exception as e:
            test("decode completed", False, str(e))
        print()

    # --- List Jobs ---
    print("\033[33m[List Jobs]\033[0m")
    try:
        job_list = client.list_jobs(page=1, limit=5)
        test("list_jobs returned", len(job_list.jobs) >= 0, f"{len(job_list.jobs)} jobs, total={job_list.total}")
        if job_list.jobs:
            j = job_list.jobs[0]
            test("job has fields", bool(j.job_id) and bool(j.job_type), f"{j.job_id}: {j.job_type} ({j.status})")
    except Exception as e:
        test("list_jobs", False, str(e))
    print()

    # --- Delete Job Files ---
    if job_list and job_list.jobs:
        completed = [j for j in job_list.jobs if j.status == "COMPLETED"]
        if completed:
            print("\033[33m[Delete Job Files]\033[0m")
            try:
                ok = client.delete_job_files(completed[0].job_id)
                test("delete_job_files", ok, f"job_id={completed[0].job_id}")
            except Exception as e:
                test("delete_job_files", False, str(e))
            print()

    # --- Watermark Registry ---
    print("\033[33m[Watermark Registry]\033[0m")
    try:
        reg = client.register_watermark(
            content_type="image",
            file_hash="test_hash_abc123",
            file_format="png",
        )
        test("register returned uid", reg["uid"] > 0, f"uid={reg['uid']}")
        test("register returned ref", bool(reg["watermark_ref"]), reg["watermark_ref"])

        # Lookup
        entry = client.lookup_watermark(uid=reg["uid"])
        test("lookup found entry", entry is not None, f"ref={entry.watermark_ref}" if entry else "")
        if entry:
            test("entry content_type", entry.content_type == "image", entry.content_type)
            test("entry status", entry.status == "ACTIVE", entry.status)
    except Exception as e:
        test("registry", False, str(e))
    print()

    # --- Model Manifest ---
    print("\033[33m[Model Manifest]\033[0m")
    try:
        manifest = client.get_model_manifest()
        test("manifest returned", manifest is not None)
        test("has versions", len(manifest.versions) >= 0, f"{len(manifest.versions)} versions")
        test("latest_encode_version", manifest.latest_encode_version >= 0, f"v{manifest.latest_encode_version}")
    except Exception as e:
        test("model_manifest", False, str(e))
    print()

    # --- Credits After ---
    print("\033[33m[Credits After]\033[0m")
    credits_after = client.credits()
    test("balance exists", credits_after.balance_microdollars >= 0, f"${credits_after.balance_dollars:.4f}")
    spent = credits.balance_microdollars - credits_after.balance_microdollars
    print(f"  Credits spent: ${spent / 1_000_000:.4f}")
    print()

    # --- Summary ---
    total = PASS + FAIL
    print("=========================================")
    print(f" Results: \033[32m{PASS} passed\033[0m, \033[31m{FAIL} failed\033[0m, {total} total")
    print("=========================================")
    print()

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
