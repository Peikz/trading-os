"""Free pages and tags (`trading_os/pages.py`), on a throw-away folder with made-up text."""

import datetime as dt

import pytest

from trading_os import pages


def test_hashtags_are_lowercase_words_outside_code_and_headings():
    text = (
        "# Heading\nGood #Setup and #late-entry, not #1 or a#b or `#code` or [[#x]]\n#setup again"
    )
    assert pages.hashtags(text) == ["setup", "late-entry"]
    assert pages.hashtags("```\n#fenced\n```\n#open_tag") == ["open_tag"]
    assert pages.hashtags("") == []


def test_typed_tags_and_text_tags_are_the_same_tags():
    assert pages.split_tags("Ep, late-entry #Ep; x y") == ["ep", "late-entry", "x", "y"]
    assert pages.all_tags("ep", "see #flag and #ep") == ["ep", "flag"]
    assert pages.normalize_tag("9bad") == "" and pages.normalize_tag("#Good") == "good"


def test_a_page_round_trips_and_slugs_are_unique(tmp_path):
    day = dt.date(2026, 1, 5)
    a = pages.create(tmp_path, "Weekly plan: Q1", "Body with #ops", ["plan"], today=day)
    b = pages.create(tmp_path, "Weekly plan: Q1", today=day)
    assert (a.slug, b.slug) == ("weekly-plan-q1", "weekly-plan-q1-2")
    assert a.title == "Weekly plan: Q1" and a.created == "2026-01-05"
    assert a.tags == ["plan"] and a.text == "Body with #ops"
    assert pages.load(tmp_path, a.slug).as_dict()["all_tags"] == ["plan", "ops"]
    raw = (pages.folder(tmp_path) / "weekly-plan-q1.md").read_text(encoding="utf-8")
    assert raw.startswith("---\ntitle:") and raw.endswith("---\nBody with #ops\n")


def test_save_overwrites_only_what_is_given_and_delete_removes(tmp_path):
    p = pages.create(tmp_path, "Alpha", "one", today=dt.date(2026, 2, 2))
    pages.save(tmp_path, p.slug, text="two")
    again = pages.load(tmp_path, p.slug)
    assert again.text == "two" and again.title == "Alpha" and again.created == "2026-02-02"
    pages.save(tmp_path, p.slug, title="Beta", tags=["x"])
    again = pages.load(tmp_path, p.slug)
    assert again.title == "Beta" and again.tags == ["x"] and again.text == "two"
    assert again.slug == p.slug  # renaming keeps the file
    assert [x.slug for x in pages.list_pages(tmp_path)] == [p.slug]
    pages.delete(tmp_path, p.slug)
    assert pages.list_pages(tmp_path) == [] and pages.load(tmp_path, p.slug) is None
    with pytest.raises(KeyError):
        pages.delete(tmp_path, p.slug)


def test_a_slug_cannot_leave_the_folder(tmp_path):
    for bad in ("../x", "a/b", "", ".hidden", "A"):
        with pytest.raises(ValueError):
            pages.load(tmp_path, bad)


def test_a_hand_edited_page_without_front_matter_still_loads(tmp_path):
    folder = pages.folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "loose-note.md").write_text("Just text #idea\n", encoding="utf-8")
    p = pages.load(tmp_path, "loose-note")
    assert p.title == "loose note" and p.text == "Just text #idea"
    assert p.as_dict()["all_tags"] == ["idea"]
