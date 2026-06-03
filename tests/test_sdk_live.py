"""
Live SDK integration test against the Verda Enterprise API.

Usage:
    VERDA_API_KEY=vk_... python tests/test_sdk_live.py

Requires test media files in ~/Downloads/verda-sdk-test-files/
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
    if image_file:
        print("\033[33m[Image Encode]\033[0m")
        print(f"  Encoding {image_file.name}...")
        try:
            result = client.encode(str(image_file))
            test("encode completed", result.status in ("COMPLETED", "3"), result.status)
            test("watermark_id returned", bool(result.watermark_id), result.watermark_id)
            test("download_url returned", bool(result.download_url), result.download_url[:80] + "..." if result.download_url else "")

            # Decode the watermarked file to verify
            if result.download_url:
                print()
                print("\033[33m[Image Decode — verify watermark]\033[0m")
                print(f"  Decoding watermarked image...")
                decode_result = client.decode(url=result.download_url, content_type="image", file_format=image_file.suffix.lstrip("."))
                test("decode completed", decode_result.status in ("COMPLETED", "3"), decode_result.status)
                test("watermark found", decode_result.match, f"match={decode_result.match}")
                if decode_result.watermark_id:
                    test("watermark_id matches", decode_result.watermark_id == result.watermark_id,
                         f"encoded={result.watermark_id}, decoded={decode_result.watermark_id}")
        except Exception as e:
            test("encode completed", False, str(e))
        print()

    # --- Image Decode (original, no watermark) ---
    if image_file:
        print("\033[33m[Image Decode — original (no watermark)]\033[0m")
        print(f"  Decoding {image_file.name}...")
        try:
            result = client.decode(str(image_file))
            test("decode completed", result.status in ("COMPLETED", "3", "FAILED", "4"), result.status)
            test("no watermark found (expected)", not result.match, f"match={result.match}")
        except Exception as e:
            test("decode completed", False, str(e))
        print()

    # --- Video Encode (async, don't wait) ---
    if video_file:
        print("\033[33m[Video Encode — async]\033[0m")
        print(f"  Submitting {video_file.name} (not waiting)...")
        try:
            job_id = client.encode(str(video_file), wait=False)
            test("job_id returned", bool(job_id), job_id)

            job = client.get_job(job_id)
            test("job status is QUEUED/PROCESSING", job.status in ("QUEUED", "PROCESSING", "1", "2"), job.status)
        except Exception as e:
            test("encode submitted", False, str(e))
        print()

    # --- Audio Encode (async, don't wait) ---
    if audio_file:
        print("\033[33m[Audio Encode — async]\033[0m")
        print(f"  Submitting {audio_file.name} (not waiting)...")
        try:
            job_id = client.encode(str(audio_file), wait=False)
            test("job_id returned", bool(job_id), job_id)

            job = client.get_job(job_id)
            test("job status is QUEUED/PROCESSING", job.status in ("QUEUED", "PROCESSING", "1", "2"), job.status)
        except Exception as e:
            test("encode submitted", False, str(e))
        print()

    # --- URL Encode ---
    print("\033[33m[Encode via URL]\033[0m")
    try:
        job_id = client.encode(url="https://picsum.photos/200/300.jpg", wait=False)
        test("job_id returned", bool(job_id), job_id)
    except Exception as e:
        test("url encode submitted", False, str(e))
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
