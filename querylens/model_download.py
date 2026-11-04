"""Fetch pinned public model weights and verify their published SHA-256."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPOSITORY = "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF"
FILENAME = "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"


def download(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        f"https://huggingface.co/api/models/{REPOSITORY}?blobs=true",
        headers={"User-Agent": "QueryLens-local-setup/0.3"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    file = next(s for s in metadata["siblings"] if s["rfilename"] == FILENAME)
    expected_hash = file["lfs"]["sha256"]
    revision = metadata["sha"]
    destination = directory / FILENAME
    if (
        destination.exists()
        and hashlib.file_digest(destination.open("rb"), "sha256").hexdigest() == expected_hash
    ):
        print(f"Verified existing model: {destination}", flush=True)
        return destination
    url = f"https://huggingface.co/{REPOSITORY}/resolve/{revision}/{FILENAME}?download=true"
    part = destination.with_suffix(".gguf.part")
    digest = hashlib.sha256()
    downloaded = 0
    print(f"Downloading {REPOSITORY} / {FILENAME} ({file['size'] / 1e9:.2f} GB)", flush=True)
    with urllib.request.urlopen(url, timeout=90) as response, part.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if downloaded // (100 * 1024 * 1024) != (downloaded - len(chunk)) // (
                100 * 1024 * 1024
            ):
                print(f"Downloaded {downloaded / 1e6:.0f} MB", flush=True)
    if digest.hexdigest() != expected_hash or downloaded != file["size"]:
        raise RuntimeError("Model checksum or size verification failed; partial file retained.")
    os.replace(part, destination)
    manifest = {
        "repository": REPOSITORY,
        "revision": revision,
        "filename": FILENAME,
        "sha256": expected_hash,
        "bytes": downloaded,
        "source": url,
        "license": "Apache-2.0",
    }
    (directory / "model-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Verified model SHA-256: {expected_hash}", flush=True)
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(".querylens/models"))
    download(parser.parse_args().directory)
