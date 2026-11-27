"""Download the model files listed in models.toml and check their SHA-256.

Standard library only; needs Python 3.11 or newer (for tomllib). Run from ml/:

  python3 scripts/download_models.py                 # every model in models.toml
  python3 scripts/download_models.py NAME ...        # only the named models
  python3 scripts/download_models.py --check         # check what is there; download nothing
  python3 scripts/download_models.py --dest DIR      # unpack under DIR instead of ml/

A model whose files already match their SHA-256 is skipped. Each archive is first
written to a temporary file and checked; then every file inside it is checked and
renamed into place, so a failed or partial download never replaces a good file.

A private GitHub release is fetched with the GitHub CLI when it is installed and signed
in, otherwise with the REST API and the token in GITHUB_TOKEN.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.exit(
        "This script needs Python 3.11 or newer; this is "
        f"{sys.version_info.major}.{sys.version_info.minor}. Try:\n"
        "  uv run --no-project --python 3.12 python scripts/download_models.py"
    )

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ML_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ML_ROOT / "models.toml"
USER_AGENT = "news-bot-download-models"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1 << 20


class DownloadError(Exception):
    """A problem the person running the script can fix; the message says how."""


class _NoRedirect(HTTPRedirectHandler):
    """Stop at a redirect, so the signed storage URL is fetched without our token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def load_models(path: Path) -> list[dict]:
    with path.open("rb") as handle:
        models = tomllib.load(handle).get("model", [])
    names = [model.get("name") for model in models]
    if len(names) != len(set(names)):
        raise DownloadError(f"{path.name} lists a model name twice")
    for model in models:
        _validate(model)
    return models


def _validate(model: dict) -> None:
    name = model.get("name")
    if not isinstance(name, str) or not name:
        raise DownloadError("every [[model]] needs a name")
    unpack_to = PurePosixPath(str(model.get("unpack_to", "")))
    if not unpack_to.parts or unpack_to.is_absolute() or ".." in unpack_to.parts:
        raise DownloadError(f"{name}: unpack_to must be a folder inside ml/")
    if not SHA256.match(str(model.get("sha256", ""))) or not isinstance(model.get("size"), int):
        raise DownloadError(f"{name}: needs the archive's sha256 and size")
    files = model.get("files")
    if not isinstance(files, dict) or not files:
        raise DownloadError(f"{name}: [model.files] must list every file and its sha256")
    for file_name, digest in files.items():
        if "/" in file_name or file_name in {"", ".", ".."} or not SHA256.match(str(digest)):
            raise DownloadError(f"{name}: bad entry for {file_name!r} in [model.files]")
    source = model.get("source", {})
    github = all(isinstance(source.get(key), str) for key in ("github_repo", "tag", "asset"))
    url = isinstance(source.get("url"), str) and urlsplit(source["url"]).scheme == "https"
    if github == url:
        raise DownloadError(f"{name}: source needs either github_repo, tag and asset, or one https url")


def mismatched_files(model: dict, target: Path) -> list[str]:
    """Files that are missing or differ from models.toml."""
    return [
        file_name for file_name, digest in model["files"].items()
        if not (target / file_name).is_file() or sha256_of(target / file_name) != digest
    ]


def _gh_signed_in() -> bool:
    if shutil.which("gh") is None:
        return False
    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
    return result.returncode == 0


def _download_with_gh(source: dict, out: Path) -> None:
    command = [
        "gh", "release", "download", source["tag"], "--repo", source["github_repo"],
        "--pattern", source["asset"], "--output", str(out), "--clobber",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise DownloadError(f"the GitHub CLI could not download {source['asset']}: {result.stderr.strip()}")


def _copy_response(response, out: Path) -> None:
    with out.open("wb") as handle:
        shutil.copyfileobj(response, handle, CHUNK)


def _download_with_token(source: dict, out: Path, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    release_url = (
        f"https://api.github.com/repos/{source['github_repo']}/releases/tags/{quote(source['tag'], safe='')}"
    )
    try:
        with urlopen(Request(release_url, headers={**headers, "Accept": "application/vnd.github+json"}),
                     timeout=60) as response:
            release = json.load(response)
    except HTTPError as error:
        raise DownloadError(
            f"GitHub refused to show release {source['tag']} of {source['github_repo']} "
            f"(HTTP {error.code}). Check that GITHUB_TOKEN can read that repository."
        ) from error
    asset = next((item for item in release.get("assets", []) if item.get("name") == source["asset"]), None)
    if asset is None:
        raise DownloadError(f"release {source['tag']} has no file named {source['asset']}")
    # GitHub answers with the bytes, or with a redirect to a signed storage URL. That URL
    # carries its own permission and rejects a second one, so it gets no Authorization.
    request = Request(asset["url"], headers={**headers, "Accept": "application/octet-stream"})
    try:
        response = build_opener(_NoRedirect).open(request, timeout=60)
    except HTTPError as error:
        location = error.headers.get("Location", "")
        if error.code not in {301, 302, 303, 307, 308} or urlsplit(location).scheme != "https":
            raise DownloadError(f"GitHub refused to send {source['asset']} (HTTP {error.code})") from error
        response = urlopen(Request(location, headers={"User-Agent": USER_AGENT}), timeout=300)
    with response:
        _copy_response(response, out)


def _download_url(url: str, out: Path) -> None:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=300) as response:
        _copy_response(response, out)


def fetch(model: dict, out: Path) -> None:
    source = model["source"]
    if "url" in source:
        _download_url(source["url"], out)
        return
    problems = []
    if _gh_signed_in():
        try:
            _download_with_gh(source, out)
            return
        except DownloadError as error:
            problems.append(str(error))
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        _download_with_token(source, out, token)
        return
    problems.append(
        f"{source['asset']} is in the private GitHub repository {source['github_repo']}. "
        "To download it, either install the GitHub CLI and sign in with `gh auth login`, "
        "or set GITHUB_TOKEN to a token that can read that repository. Then run this again."
    )
    raise DownloadError("\n".join(problems))


def unpack(model: dict, archive: Path, target: Path) -> None:
    """Check every file in the archive, then rename each one into place."""
    expected = model["files"]
    target.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            names = [member.name for member in members]
            if sorted(names) != sorted(expected) or not all(member.isfile() for member in members):
                raise DownloadError(f"{model['name']}: the archive holds {names}, not {sorted(expected)}")
            for member in members:
                handle, temporary = tempfile.mkstemp(dir=target, prefix=f".{member.name}.", suffix=".part")
                staged[member.name] = Path(temporary)
                with os.fdopen(handle, "wb") as out, tar.extractfile(member) as data:
                    shutil.copyfileobj(data, out, CHUNK)
                if sha256_of(staged[member.name]) != expected[member.name]:
                    raise DownloadError(f"{model['name']}: {member.name} does not match its sha256 in models.toml")
        for file_name, temporary in staged.items():
            temporary.chmod(0o644)
            os.replace(temporary, target / file_name)
        staged.clear()
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def install(model: dict, dest: Path, check_only: bool) -> bool:
    target = dest / model["unpack_to"]
    label = f"{model['name']} ({target})"
    wrong = mismatched_files(model, target)
    if not wrong:
        print(f"ok        {label}: every file matches its sha256", flush=True)
        return True
    if check_only:
        print(f"MISSING   {label}: missing or different: {', '.join(wrong)}", flush=True)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{model['name']}.", suffix=".part")
    os.close(handle)
    archive = Path(temporary)
    try:
        print(f"download  {model['name']}: {model['size']:,} bytes", flush=True)
        fetch(model, archive)
        size, digest = archive.stat().st_size, sha256_of(archive)
        if size != model["size"] or digest != model["sha256"]:
            raise DownloadError(
                f"{model['name']}: the download does not match models.toml "
                f"(expected {model['size']:,} bytes, sha256 {model['sha256']}; got {size:,} bytes, "
                f"sha256 {digest}). Nothing was changed."
            )
        unpack(model, archive, target)
    finally:
        archive.unlink(missing_ok=True)
    print(f"ok        {label}: downloaded; every file matches its sha256", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and check the model files in models.toml.")
    parser.add_argument("names", nargs="*", help="models to fetch (default: all)")
    parser.add_argument("--check", action="store_true", help="only check the files already there")
    parser.add_argument("--dest", type=Path, default=ML_ROOT, help="folder that unpack_to is relative to")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="the models.toml to read")
    args = parser.parse_args(argv)
    try:
        models = load_models(args.manifest)
        unknown = sorted(set(args.names) - {model["name"] for model in models})
        if unknown:
            raise DownloadError(f"not in {args.manifest.name}: {', '.join(unknown)}")
        chosen = [model for model in models if not args.names or model["name"] in args.names]
        results = [install(model, args.dest.resolve(), args.check) for model in chosen]
    except (DownloadError, OSError, URLError, tarfile.TarError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
