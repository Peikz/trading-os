"""On-demand release data: fetch only what's missing, in batches, and keep the cache capped."""

import json
import os
import time
from types import SimpleNamespace

from trading_os import remote_data as rd


class FakeGh:
    def __init__(self, files):
        self.files, self.calls = files, []

    def __call__(self, args, timeout=0):
        self.calls.append(args)
        if args[:2] == ["release", "view"]:
            listing = [{"name": n, "size": len(b)} for n, b in self.files.items()]
            return SimpleNamespace(returncode=0, stdout=json.dumps({"assets": listing}))
        folder = args[args.index("-D") + 1]
        names = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        for name in names:
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(self.files[name])
        return SimpleNamespace(returncode=0, stdout="")


def test_fetch_downloads_only_missing_files_in_one_call(tmp_path, monkeypatch):
    fake = FakeGh({"a_1.parquet": b"x" * 10, "a_2.parquet": b"y" * 10, "b.parquet": b"z"})
    monkeypatch.setattr(rd, "_gh", fake)
    rd._listings.clear()
    paths = rd.fetch("o/r", "tag", "a_*.parquet", cache=tmp_path)
    assert sorted(p.name for p in paths) == ["a_1.parquet", "a_2.parquet"]
    downloads = [c for c in fake.calls if c[:2] == ["release", "download"]]
    assert len(downloads) == 1 and downloads[0].count("-p") == 2
    rd.fetch("o/r", "tag", "a_*.parquet", cache=tmp_path)  # already here: no download
    assert len([c for c in fake.calls if c[:2] == ["release", "download"]]) == 1


def test_prune_drops_the_least_recently_used_files(tmp_path):
    old, new = tmp_path / "old.bin", tmp_path / "new.bin"
    old.write_bytes(b"o" * 60)
    new.write_bytes(b"n" * 60)
    past = time.time() - 3600
    os.utime(old, (past, past))
    left = rd.prune(tmp_path, limit=100)
    assert not old.exists() and new.exists() and left == 60


def test_clear_and_size(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "f.bin").write_bytes(b"1234")
    assert rd.size(tmp_path) == 4
    rd.clear(tmp_path)
    assert rd.size(tmp_path) == 0
