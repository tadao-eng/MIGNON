"""歳時記の SQLite ストア。

正本は `data/saijiki.json`。`haiku build-db` で SQLite へ展開し、以降は SQLite を
読む。SQLite が無い場合は JSON から直接ロードするので、初回実行でも動作する。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import kana as kana_util

SCHEMA = """
CREATE TABLE IF NOT EXISTS kigo (
    id        INTEGER PRIMARY KEY,
    word      TEXT NOT NULL,
    kana      TEXT NOT NULL,
    season    TEXT NOT NULL,
    category  TEXT NOT NULL,
    note      TEXT
);
CREATE TABLE IF NOT EXISTS kigo_alias (
    kigo_id   INTEGER NOT NULL REFERENCES kigo(id) ON DELETE CASCADE,
    surface   TEXT NOT NULL,
    kind      TEXT NOT NULL  -- 'word' | 'kana' | 'alias'
);
CREATE INDEX IF NOT EXISTS idx_alias_surface ON kigo_alias(surface);
CREATE INDEX IF NOT EXISTS idx_kigo_season ON kigo(season);

CREATE TABLE IF NOT EXISTS famous_haiku (
    id     INTEGER PRIMARY KEY,
    text   TEXT NOT NULL,
    kana   TEXT NOT NULL,
    author TEXT
);
"""


@dataclass(frozen=True)
class Kigo:
    id: int
    word: str
    kana: str
    season: str
    category: str
    note: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def surfaces(self) -> tuple[str, ...]:
        return (self.word, *self.aliases)


@dataclass(frozen=True)
class FamousHaiku:
    text: str
    kana: str
    author: str = ""


@dataclass
class Saijiki:
    kigo: list[Kigo] = field(default_factory=list)
    famous: list[FamousHaiku] = field(default_factory=list)

    def reading_dictionary(self) -> dict[str, str]:
        """歳時記の見出し語を読み推定のフォールバック辞書として流用する。"""
        d: dict[str, str] = {}
        for k in self.kigo:
            if kana_util.contains_kanji(k.word):
                d.setdefault(k.word, k.kana)
        return d

    def seasons(self) -> list[str]:
        seen: list[str] = []
        for k in self.kigo:
            if k.season not in seen:
                seen.append(k.season)
        return seen


def default_data_dir() -> Path:
    """パッケージからの相対で `data/` を探す（リポジトリ直下配置を想定）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "saijiki.json"
        if candidate.exists():
            return parent / "data"
    return here.parent / "data"


def default_db_path() -> Path:
    return default_data_dir() / "saijiki.sqlite3"


def load_json(data_dir: Path | None = None) -> Saijiki:
    data_dir = data_dir or default_data_dir()
    saijiki_path = data_dir / "saijiki.json"
    famous_path = data_dir / "famous_haiku.json"

    raw = json.loads(saijiki_path.read_text(encoding="utf-8"))
    kigo: list[Kigo] = []
    for idx, entry in enumerate(raw["entries"], start=1):
        kigo.append(
            Kigo(
                id=idx,
                word=entry["word"],
                kana=entry["kana"],
                season=entry["season"],
                category=entry["category"],
                note=entry.get("note", ""),
                aliases=tuple(entry.get("aliases", [])),
            )
        )

    famous: list[FamousHaiku] = []
    if famous_path.exists():
        fraw = json.loads(famous_path.read_text(encoding="utf-8"))
        for entry in fraw["entries"]:
            famous.append(
                FamousHaiku(
                    text=entry["text"],
                    kana=entry.get("kana") or kana_util.kana_only(entry["text"]),
                    author=entry.get("author", ""),
                )
            )
    return Saijiki(kigo=kigo, famous=famous)


def build_db(data_dir: Path | None = None, db_path: Path | None = None) -> Path:
    """JSON から SQLite を（再）構築する。"""
    data = load_json(data_dir)
    db_path = db_path or default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for k in data.kigo:
            conn.execute(
                "INSERT INTO kigo (id, word, kana, season, category, note) VALUES (?,?,?,?,?,?)",
                (k.id, k.word, k.kana, k.season, k.category, k.note),
            )
            rows = [(k.id, k.word, "word"), (k.id, k.kana, "kana")]
            rows += [(k.id, a, "alias") for a in k.aliases]
            conn.executemany(
                "INSERT INTO kigo_alias (kigo_id, surface, kind) VALUES (?,?,?)", rows
            )
        conn.executemany(
            "INSERT INTO famous_haiku (text, kana, author) VALUES (?,?,?)",
            [(f.text, f.kana, f.author) for f in data.famous],
        )
        conn.commit()
    return db_path


def load(data_dir: Path | None = None, db_path: Path | None = None) -> Saijiki:
    """SQLite があればそこから、無ければ JSON から歳時記をロードする。"""
    db_path = db_path or default_db_path()
    if not db_path.exists():
        return load_json(data_dir)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        aliases: dict[int, list[str]] = {}
        for row in conn.execute("SELECT kigo_id, surface FROM kigo_alias WHERE kind='alias'"):
            aliases.setdefault(row["kigo_id"], []).append(row["surface"])
        kigo = [
            Kigo(
                id=row["id"],
                word=row["word"],
                kana=row["kana"],
                season=row["season"],
                category=row["category"],
                note=row["note"] or "",
                aliases=tuple(aliases.get(row["id"], [])),
            )
            for row in conn.execute("SELECT * FROM kigo ORDER BY id")
        ]
        famous = [
            FamousHaiku(text=row["text"], kana=row["kana"], author=row["author"] or "")
            for row in conn.execute("SELECT * FROM famous_haiku ORDER BY id")
        ]
    return Saijiki(kigo=kigo, famous=famous)
