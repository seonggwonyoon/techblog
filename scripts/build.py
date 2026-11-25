"""Build the offline HTML directory and OPML subscription file from catalog.json."""

import argparse
from collections import Counter
from datetime import date
from html import escape
import json
from pathlib import Path
import re
from string import Template
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REGIONS = ("국내", "해외")
QUIET = "최근 1년 새 글 없음"
ARCHIVE = "아카이브"
FOLDED = {QUIET: "quiet", ARCHIVE: "archive"}


def is_text(value):
    return isinstance(value, str) and bool(value.strip()) and value.splitlines() == [value]


def validate_url(url):
    if not isinstance(url, str) or re.search(r'[\s<>|"\\]', url):
        raise ValueError(f"올바른 URL이 필요합니다 ({url!r})")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None:
        raise ValueError(f"공개 HTTP(S) 주소가 필요합니다 ({url})")
    # Accessing port also validates its syntax and range.
    _ = parts.port


def validate_activity(review):
    if not isinstance(review, dict) or set(review) != {"published", "checked", "post"}:
        raise ValueError("activity에 published, checked, post가 필요합니다.")
    for field in ("published", "checked"):
        value = review[field]
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"{field}에 YYYY-MM-DD 날짜가 필요합니다.")
    if review["published"] > review["checked"]:
        raise ValueError("마지막 발행일이 확인일보다 늦습니다.")
    validate_url(review["post"])


def no_recent_posts(blog):
    review = blog.get("activity")
    if not review:
        return False
    checked = date.fromisoformat(review["checked"])
    # A leap-day review uses February 28 as the start of the previous year-long window.
    day = 28 if (checked.month, checked.day) == (2, 29) else checked.day
    cutoff = checked.replace(year=checked.year - 1, day=day)
    return date.fromisoformat(review["published"]) < cutoff


def group_blogs(blogs):
    groups = {name: [] for name in (*REGIONS, QUIET, ARCHIVE)}
    for blog in blogs:
        group = blog["region"]
        if blog.get("archive"):
            group = ARCHIVE
        elif no_recent_posts(blog):
            group = QUIET
        groups[group].append(blog)
    for group in FOLDED:
        groups[group].sort(key=lambda b: b.get("activity", {}).get("published", ""), reverse=True)
    return groups


def group_description(group, blogs):
    if group == ARCHIVE:
        return "글을 옮긴 팀의 예전 발행처와 원문 저장소입니다."
    dates = sorted({b["activity"]["checked"] for b in blogs})
    checked = dates[0] if len(dates) == 1 else f"{dates[0]}~{dates[-1]}"
    return f"{checked} 점검 기준으로 등록된 발행처에 최근 1년간 새 글이 없었습니다. 마지막 발행일은 한국 시간 기준입니다."


def load_catalog():
    blogs = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(blogs, list) or not blogs:
        raise ValueError("catalog.json에 블로그 목록이 필요합니다.")
    allowed = {"name", "region", "url", "topics", "aliases", "feed", "feedScope", "archive", "archiveNote", "activity"}
    seen = {key: set() for key in ("name", "url", "feed")}
    for number, blog in enumerate(blogs, 1):
        try:
            if not isinstance(blog, dict) or set(blog) - allowed:
                raise ValueError("알 수 없는 항목 형식 또는 필드입니다.")
            if not is_text(blog.get("name")) or blog.get("region") not in REGIONS:
                raise ValueError("이름과 지역(국내 또는 해외)을 확인하세요.")
            for key in ("topics", "aliases"):
                values = blog.get(key, [])
                if not isinstance(values, list) or not all(is_text(v) for v in values):
                    raise ValueError(f"{key}에는 문자열 목록이 필요합니다.")
                if len(set(values)) != len(values) or (key == "topics" and not values):
                    raise ValueError(f"{key} 목록을 확인하세요.")
            if not isinstance(blog.get("archive", False), bool):
                raise ValueError("archive 값은 true 또는 false입니다.")
            if "archiveNote" in blog and (not blog.get("archive") or not is_text(blog["archiveNote"])):
                raise ValueError("archiveNote에는 아카이브로 보관한 이유를 적어 주세요.")
            if "activity" in blog:
                validate_activity(blog["activity"])
            validate_url(blog.get("url"))
            if "feed" in blog:
                validate_url(blog["feed"])
            if "feedScope" in blog and ("feed" not in blog or blog["feedScope"] != "all"):
                raise ValueError("feedScope은 공용 피드 주소가 있는 항목에만 all로 지정합니다.")
            for key in seen:
                if key in blog:
                    value = blog[key].casefold() if key == "name" else blog[key].rstrip("/")
                    if value in seen[key]:
                        raise ValueError(f"중복된 {key} ({blog[key]})")
                    seen[key].add(value)
        except ValueError as error:
            raise ValueError(f"catalog.json {number}번째 항목 — {error}") from error
    return blogs


def feed_label(blog):
    return "전체 RSS" if blog.get("feedScope") == "all" else "RSS"


def render_entry(blog):
    name, url, region = (escape(blog[key]) for key in ("name", "url", "region"))
    aliases = escape(" ".join(blog.get("aliases", [])))
    parts = urlsplit(blog["url"])
    address = parts.hostname
    if address in {"medium.com", "github.com"}:
        address += "/" + parts.path.strip("/").split("/")[0]
    archive_attr = " data-archive" if blog.get("archive") else ""
    quiet_attr = " data-quiet" if no_recent_posts(blog) else ""
    note = f' <small class="archive-label">{escape(blog["archiveNote"])}</small>' if blog.get("archiveNote") else ""
    review_info = ""
    if "activity" in blog:
        review = blog["activity"]
        published = review["published"]
        review_info = (f'\n              <a class="last-post" href="{escape(review["post"])}" title="{review["checked"]} 확인" '
                       f'aria-label="{name} 마지막 글 {published}">마지막 글 <time datetime="{published}">{published}</time></a>')
    tags = ", ".join(f'<span class="tag">{escape(topic)}</span>' for topic in blog["topics"])
    feed = ""
    if "feed" in blog:
        label = feed_label(blog)
        feed = (f'<a class="feed-link" href="{escape(blog["feed"])}" aria-label="{name} {label} 주소">'
                f'<svg class="icon" aria-hidden="true"><use href="#icon-rss"/></svg>{label}</a>')
    return f"""<li class="entry" data-region="{region}" data-aliases="{aliases}"{archive_attr}{quiet_attr}>
            <div class="identity">
              <a class="blog-name" href="{url}">{name}</a>{note}
              <div class="address">{region} <span aria-hidden="true">·</span> {escape(address)}</div>{review_info}
            </div>
            <div class="tags">{tags}</div>
            <div class="entry-feed">{feed}</div>
          </li>"""


def render_folded(section, blogs):
    rows = "\n".join(render_entry(blog) for blog in blogs)
    return f"""<details class="blog-group" id="{FOLDED[section]}-blogs">
          <summary><svg class="icon chevron" aria-hidden="true"><use href="#icon-chevron"/></svg>
            {section} <span class="group-count">{len(blogs)}곳</span></summary>
          <p>{group_description(section, blogs)}</p>
          <ul class="blog-list">
            {rows}
          </ul>
        </details>"""


def render_directory(blogs):
    counts = Counter(topic for blog in blogs for topic in blog["topics"])
    controls = []
    for topic, count in [("", len(blogs)), *sorted(counts.items())]:
        checked = "" if topic else " checked"
        value = escape(topic)
        controls.append(
            f'<label><input form="filters" type="radio" name="topic" value="{value}"{checked}>'
            f'<span>{value or "전체 주제"} <small>{count}</small></span></label>'
        )
    template = Template((ROOT / "templates/index.html").read_text(encoding="utf-8"))
    groups = group_blogs(blogs)
    return template.substitute(
        topic_controls="\n          ".join(controls),
        entries="\n          ".join(render_entry(blog) for region in REGIONS for blog in groups[region]),
        folded_groups="\n        ".join(render_folded(name, groups[name]) for name in FOLDED if groups[name]),
        blog_count=len(blogs),
        feed_count=sum("feed" in blog for blog in blogs),
    )


def render_opml(blogs):
    root = ET.Element("opml", version="2.0")
    ET.SubElement(ET.SubElement(root, "head"), "title").text = "techblog 구독 목록"
    body = ET.SubElement(root, "body")
    for region in REGIONS:
        feeds = [b for b in blogs if b["region"] == region and "feed" in b]
        if feeds:
            group = ET.SubElement(body, "outline", text=region)
            for blog in feeds:
                ET.SubElement(group, "outline", type="rss", text=blog["name"], title=blog["name"],
                              htmlUrl=blog["url"], xmlUrl=blog["feed"])
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8") + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report out-of-date files without writing them")
    args = parser.parse_args()
    blogs = load_catalog()
    outputs = {
        ROOT / "docs/index.html": render_directory(blogs),
        ROOT / "docs/feeds.opml": render_opml(blogs),
    }
    stale = []
    for path, content in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if args.check and stale:
        sys.exit("다시 생성하세요: " + ", ".join(stale))
    print(f"블로그 {len(blogs)}곳, 피드 {sum('feed' in b for b in blogs)}개")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
