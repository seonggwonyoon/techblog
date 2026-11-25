"""Check catalog URLs with curl and validate the article feeds."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

from build import load_catalog


FEED_LIMIT = 16 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; TechblogDirectory/1.0; +https://github.com/seonggwonyoon/techblog)"
ATOM = "{http://www.w3.org/2005/Atom}"
RSS1 = "{http://purl.org/rss/1.0/}"


def check_feed(path):
    if path.stat().st_size > FEED_LIMIT:
        return "직접 확인", "피드가 검사 크기 한도를 초과했습니다."
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, LookupError, ValueError) as error:
        return "오류", f"피드 XML 구문 오류 ({error})"
    if root.tag == "rss":
        item = root.find("./channel/item")
    elif root.tag == ATOM + "feed":
        item = root.find(ATOM + "entry")
    elif root.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF":
        item = root.find(RSS1 + "item")
    else:
        return "오류", "RSS 또는 Atom 문서가 아닙니다."
    if item is None:
        return "직접 확인", "피드에 글 항목이 없습니다."
    return "정상", ""


def check_url(url, is_feed):
    with TemporaryDirectory() as folder:
        body = Path(folder) / "feed.xml"
        result = subprocess.run([
            "curl", "--disable", "--silent", "--show-error", "--location", "--compressed",
            "--proto", "=http,https", "--proto-redir", "=http,https",
            "--connect-timeout", "6", "--max-time", "18", "--retry", "1", "--retry-max-time", "25",
            "--max-filesize", str(FEED_LIMIT), "--user-agent", USER_AGENT,
            "--output", str(body) if is_feed else os.devnull,
            "--write-out", "%{http_code}\n%{url_effective}", "--", url,
        ], capture_output=True, text=True)
        code, _, destination = result.stdout.partition("\n")
        if code in {"401", "403", "429"}:
            return "직접 확인", f"HTTP {code}"
        if result.returncode == 63:
            return "직접 확인", "응답이 검사 크기 한도를 초과했습니다."
        if result.returncode:
            return "오류", result.stderr.strip()
        if not code.startswith("2"):
            return "오류", f"HTTP {code}"
        if is_feed:
            status, detail = check_feed(body)
            if status != "정상":
                return status, detail
        if destination.rstrip("/") != url.rstrip("/"):
            return "직접 확인", f"이동 → {destination}"
        return "정상", ""


def check(target):
    name, kind, url = target
    status, detail = check_url(url, kind == "피드")
    return status, f"{name} ({kind})  {url}  {detail}"


def main():
    if not shutil.which("curl"):
        sys.exit("네트워크 점검에 필요한 curl을 찾을 수 없습니다.")
    targets = []
    for blog in load_catalog():
        targets.append((blog["name"], "블로그", blog["url"]))
        if "feed" in blog:
            targets.append((blog["name"], "피드", blog["feed"]))
    counts = Counter()
    with ThreadPoolExecutor(max_workers=6) as workers:
        for status, message in workers.map(check, targets):
            counts[status] += 1
            if status != "정상":
                print(f"[{status}] {message}", flush=True)
    print(f"주소 {len(targets)}개 · 정상 {counts['정상']} · 직접 확인 {counts['직접 확인']} · 오류 {counts['오류']}")
    return 1 if counts["오류"] or not counts["정상"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
