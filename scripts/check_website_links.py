"""Check website links against the files shipped to Pages and this checkout.

Network requests are intentionally excluded: the repository and Pages site stay
private until publication, so their public URLs currently return 404.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"
PAGES = sorted(SITE.glob("*.html"))
PAGE_HOST = "veles-labs.github.io"
REPO_PREFIX = "/veles-labs/casthon/"
RAW_PREFIX = "/veles-labs/casthon/main/"


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.references: list[tuple[str, str]] = []
        self.issues: list[str] = []
        self.link_count = 0
        self.asset_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        identifier = values.get("id")
        if identifier:
            if identifier in self.ids:
                self.issues.append(f"duplicate id #{identifier}")
            self.ids.add(identifier)
        for name in ("href", "src"):
            if name in values:
                value = values[name]
                if value is None or not value.strip():
                    self.issues.append(f"empty {tag} {name}")
                else:
                    self.references.append((f"{tag} {name}", value))
                    if name == "href":
                        self.link_count += 1
                    else:
                        self.asset_count += 1
        for name in ("aria-controls", "aria-labelledby"):
            if values.get(name):
                for target in values[name].split():
                    self.references.append((name, "#" + target))


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    duplicates: Counter[str] = Counter()
    for line in path.read_text().splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match is None:
            continue
        title = re.sub(r"!?\[([^]]+)\]\([^)]*\)", r"\1", match[1])
        title = re.sub(r"<[^>]+>", "", title).replace("`", "")
        slug = re.sub(r"[^\w\- ]", "", title.casefold()).replace(" ", "-")
        count = duplicates[slug]
        duplicates[slug] += 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def target_for(source: Path, url: str) -> tuple[Path | None, str, str | None]:
    parsed = urlsplit(url)
    fragment = unquote(parsed.fragment)
    if parsed.scheme in ("http", "https"):
        if parsed.netloc == PAGE_HOST and parsed.path.startswith("/casthon/"):
            relative = parsed.path.removeprefix("/casthon/") or "index.html"
            return SITE / unquote(relative), fragment, None
        if parsed.netloc == "github.com" and parsed.path.rstrip("/") == REPO_PREFIX.rstrip("/"):
            return ROOT, fragment, None
        if parsed.netloc == "github.com" and parsed.path.startswith(REPO_PREFIX):
            route = parsed.path.removeprefix(REPO_PREFIX)
            if route.startswith(("blob/main/", "tree/main/")):
                return ROOT / unquote(route.split("/", 2)[2]), fragment, None
        if parsed.netloc == "raw.githubusercontent.com" and parsed.path.startswith(RAW_PREFIX):
            return ROOT / unquote(parsed.path.removeprefix(RAW_PREFIX)), fragment, None
        return None, fragment, None  # External destination; checked separately.
    if parsed.scheme or parsed.netloc:
        return None, fragment, "unsupported URL scheme"
    if parsed.path.startswith("/"):
        return None, fragment, "site-local paths must be relative"
    if not parsed.path and not fragment:
        return None, fragment, "link has no destination"
    target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
    if source.is_relative_to(SITE) and not target.is_relative_to(SITE):
        return None, fragment, "local link leaves the Pages artifact"
    return target, fragment, None


def main() -> int:
    parsed_pages: dict[Path, Page] = {}
    for path in PAGES:
        page = Page()
        page.feed(path.read_text())
        parsed_pages[path] = page

    references: list[tuple[Path, str, str]] = []
    issues: list[str] = []
    for path, page in parsed_pages.items():
        references.extend((path, kind, url) for kind, url in page.references)
        issues.extend(f"{path.relative_to(ROOT)}: {issue}" for issue in page.issues)

    llms = SITE / "llms.txt"
    references.extend((llms, "llms.txt link", url)
                      for url in re.findall(r"\]\(([^)]+)\)", llms.read_text()))
    for stylesheet in SITE.glob("*.css"):
        references.extend((stylesheet, "CSS url", url.strip(" \"'"))
                          for url in re.findall(r"url\(([^)]+)\)", stylesheet.read_text()))

    outside: set[str] = set()
    for source, kind, url in references:
        target, fragment, error = target_for(source, url)
        label = f"{source.relative_to(ROOT)}: {kind} {url}"
        if error:
            issues.append(f"{label}: {error}")
        elif target is None:
            outside.add(url)
        elif not target.exists():
            issues.append(f"{label}: missing {target.relative_to(ROOT)}")
        elif fragment and target.suffix == ".html":
            page = parsed_pages.get(target)
            if page is None or fragment not in page.ids:
                issues.append(f"{label}: missing HTML anchor #{fragment}")
        elif fragment and target.suffix == ".md" and fragment not in markdown_anchors(target):
            issues.append(f"{label}: missing Markdown anchor #{fragment}")

    count_links = sum(page.link_count for page in parsed_pages.values())
    count_assets = sum(page.asset_count for page in parsed_pages.values())
    print(f"Checked {len(PAGES)} pages, {count_links} HTML links, "
          f"{count_assets} HTML assets, and {len(references) - count_links - count_assets} "
          "other references.")
    print(f"{len(outside)} external URLs require separate network verification.")
    for issue in issues:
        print("ERROR:", issue)
    if not issues:
        print("All local and repository targets and anchors resolve.")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
