"""Free pages for the Journal notebook (Emil, 18 Nov 2026): a page that is not a day, a trade or a
stock. One markdown file per page in the private data repo (`data/journal/pages/<slug>.md`), a
small YAML front matter (title, created, tags) and the body as plain markdown. Written by the
owner only, through the notebook; the files are overwritten on save (git keeps the history),
unlike the append-only note logs.

Also the tag rules every note shares: a `#tag` is lowercase letters, digits, `-` and `_`,
starting with a letter, written anywhere in a text; the grading form's typed tags are the same
tags.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
HASHTAG = re.compile(r"(?<![\w&/#\[])#([A-Za-z][A-Za-z0-9_-]{0,39})(?![\w-]*\])")
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)


def folder(data_dir: Path) -> Path:
    return Path(data_dir) / "data" / "journal" / "pages"


def normalize_tag(raw: str) -> str:
    """`#Late-Entry` -> `late-entry`; empty when it is not a tag."""
    tag = str(raw or "").strip().lstrip("#").lower()
    return tag if re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", tag) else ""


def hashtags(text: str) -> list[str]:
    """The `#tags` written in a text (code spans left out), lowercase, in order, no repeats."""
    plain = CODE.sub(" ", text or "")
    out: list[str] = []
    for found in HASHTAG.findall(plain):
        tag = normalize_tag(found)
        if tag and tag not in out:
            out.append(tag)
    return out


def split_tags(typed: str | list[str] | None) -> list[str]:
    """A typed tag field (comma, space or semicolon separated, or a list) as tags."""
    parts = re.split(r"[\s,;]+", typed) if isinstance(typed, str) else list(typed or [])
    out: list[str] = []
    for part in parts:
        tag = normalize_tag(part)
        if tag and tag not in out:
            out.append(tag)
    return out


def all_tags(typed: str | list[str] | None, text: str) -> list[str]:
    """Typed tags first, then the `#tags` in the text, without repeats."""
    return list(dict.fromkeys([*split_tags(typed), *hashtags(text)]))


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:60].strip("-")
    return base or "page"


@dataclass
class Page:
    slug: str
    title: str
    created: str
    updated: str
    tags: list[str] = field(default_factory=list)
    text: str = ""

    def as_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "created": self.created,
            "updated": self.updated, "tags": self.tags, "text": self.text,
            "all_tags": all_tags(self.tags, self.text),
        }  # fmt: skip


def _path(data_dir: Path, slug: str) -> Path:
    if not SLUG.match(slug or ""):
        raise ValueError("That is not a page name.")
    return folder(data_dir) / f"{slug}.md"


def _render(title: str, created: str, tags: list[str], text: str) -> str:
    head = yaml.safe_dump(
        {"title": title, "created": created, "tags": tags},
        sort_keys=False, allow_unicode=True, default_flow_style=None,
    )  # fmt: skip
    body = text.strip("\n")
    return f"---\n{head}---\n{body}\n" if body else f"---\n{head}---\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _parse(path: Path) -> Page:
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = raw
    found = FRONT.match(raw)
    if found:
        try:
            loaded = yaml.safe_load(found.group(1))
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            meta = {}
        body = raw[found.end() :]
    stamp = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC).date().isoformat()
    created = meta.get("created")
    tags = meta.get("tags")
    return Page(
        slug=path.stem,
        title=str(meta.get("title") or path.stem.replace("-", " ")),
        created=created.isoformat() if hasattr(created, "isoformat") else str(created or stamp),
        updated=stamp,
        tags=split_tags(tags if isinstance(tags, list) else ""),
        text=body.strip("\n"),
    )


def load(data_dir: Path, slug: str) -> Page | None:
    path = _path(data_dir, slug)
    return _parse(path) if path.is_file() else None


def list_pages(data_dir: Path) -> list[Page]:
    """Every page, newest first (by the day it was last saved, then its creation day)."""
    where = folder(data_dir)
    files = sorted(where.glob("*.md")) if where.is_dir() else []
    pages = [_parse(f) for f in files if SLUG.match(f.stem)]
    return sorted(pages, key=lambda p: (p.updated, p.created, p.slug), reverse=True)


def create(
    data_dir: Path,
    title: str,
    text: str = "",
    tags: list[str] | None = None,
    today: dt.date | None = None,
) -> Page:
    """A new page; the slug comes from the title and is made unique (`plan`, `plan-2`)."""
    title = (title or "").strip() or "Untitled"
    slug, n = slugify(title), 1
    while _path(data_dir, slug).exists():
        n += 1
        slug = f"{slugify(title)}-{n}"
    created = (today or dt.date.today()).isoformat()
    _write(_path(data_dir, slug), _render(title, created, split_tags(tags), text))
    return load(data_dir, slug)  # type: ignore[return-value]


def save(
    data_dir: Path,
    slug: str,
    title: str | None = None,
    text: str | None = None,
    tags: list[str] | None = None,
) -> Page:
    """Overwrite a page's title, body or tags (what is left out stays as it was)."""
    now = load(data_dir, slug)
    if now is None:
        raise KeyError(slug)
    new_title = now.title if title is None else (title.strip() or now.title)
    _write(
        _path(data_dir, slug),
        _render(
            new_title,
            now.created,
            now.tags if tags is None else split_tags(tags),
            now.text if text is None else text,
        ),
    )
    return load(data_dir, slug)  # type: ignore[return-value]


def delete(data_dir: Path, slug: str) -> None:
    path = _path(data_dir, slug)
    if not path.is_file():
        raise KeyError(slug)
    path.unlink()
