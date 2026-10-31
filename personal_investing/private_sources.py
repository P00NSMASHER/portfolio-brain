"""Offline, read-only owner source vault for the optional personal Brain companion.

This module does not authenticate to banks or ChatGPT, call network endpoints,
modify source files, place trades, or write private data to a Git repository.
It catalogs *every* input file and reports exactly which content was indexed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / ".portfolio_brain" / "private" / "owner_sources.sqlite"
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".ged"}
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".gif", ".wav"}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".part001", ".part002", ".part003", ".part004", ".part005", ".part006", ".part007", ".part008"}
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_BYTES = 8 * 1024 * 1024
MAX_HASH_BYTES = 32 * 1024 * 1024

# Defense-in-depth: do not bring clinical records or authentication artifacts
# into a general-purpose personal portfolio. The names are not an exhaustive
# classifier: the owner must review the source directory before importing.
BLOCKED = re.compile(
    r"patient|clinical|allpt|nethealth|medical[_ -]?record|"
    r"daily[_ -]?treatment|bierman|therapy[_ -]?note|"
    r"password|credential|recovery[_ -]?code|two[_ -]?factor|"
    r"authenticator|api[_ -]?key|browser[_ -]?cookie|"
    r"where_you.re_logged_in|login[_ -]?alert|login[_ -]?protection|"
    r"device[_ -]?login|session[_ -]?token|private[_ -]?key",
    re.IGNORECASE,
)
SECRET_KEY = re.compile(r"(?:^|_)(?:api_key|access_token|refresh_token|private_key|password|secret|cookie|routing_number|account_number)(?:$|_)", re.IGNORECASE)


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _safe_db(path: Path) -> Path:
    target = path.expanduser().resolve()
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        raise ValueError("Private database must be OUTSIDE the Git repository")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        target.parent.chmod(0o700)
    if target.is_symlink():
        raise ValueError("Database symlink is not permitted")
    return target


def _connect(path: Path) -> sqlite3.Connection:
    path = _safe_db(path)
    with open(path, "ab"):
        pass
    if os.name == "posix":
        path.chmod(0o600)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            relpath TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL,
            sha256 TEXT, extension TEXT, status TEXT NOT NULL,
            detail TEXT NOT NULL, indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_text (
            relpath TEXT PRIMARY KEY REFERENCES sources(relpath) ON DELETE CASCADE,
            content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_accounts (
            source_id TEXT PRIMARY KEY, institution TEXT NOT NULL,
            name TEXT NOT NULL, account_type TEXT NOT NULL,
            balance_usd TEXT, available_usd TEXT,
            balance_date TEXT, captured_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_holdings (
            holding_id TEXT PRIMARY KEY, account_ref TEXT NOT NULL,
            security TEXT NOT NULL, ticker TEXT,
            quantity TEXT, value_usd TEXT,
            price_date TEXT, captured_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_transactions (
            source_id TEXT PRIMARY KEY, account_ref TEXT NOT NULL,
            txn_date TEXT, description TEXT NOT NULL,
            signed_amount TEXT NOT NULL, category TEXT,
            pending INTEGER NOT NULL, captured_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finance_recurring (
            source_id TEXT PRIMARY KEY, description TEXT NOT NULL,
            frequency TEXT, amount_usd TEXT, next_date TEXT,
            captured_at TEXT NOT NULL
        );
    """)
    db.commit()
    return db


def _hash_file(path: Path, max_bytes: int) -> str | None:
    if path.stat().st_size > max_bytes:
        return None
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _from_office(path: Path, suffix: str) -> str:
    # Never unpack arbitrary archive members to disk or resolve external links.
    with ZipFile(path) as archive:
        if suffix == ".docx":
            names = ["word/document.xml"]
        else:
            names = [n for n in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
            if "xl/sharedStrings.xml" in archive.namelist():
                names.insert(0, "xl/sharedStrings.xml")
        texts: list[str] = []
        size = 0
        for name in names:
            info = archive.getinfo(name)
            size += info.file_size
            if size > MAX_EXTRACTED_BYTES:
                raise ValueError("Office XML exceeds extraction limit")
            data = archive.read(name)
            root = ET.fromstring(data)
            # Word text and Excel string/cell values; no macros or formula evaluation.
            for item in root.iter():
                if item.tag.rsplit("}", 1)[-1] in {"t", "v"} and item.text:
                    texts.append(item.text)
        return "\n".join(texts)


def _extract(path: Path) -> tuple[str, str, str]:
    suffix = path.suffix.lower()
    if suffix in MEDIA_EXT or suffix in ARCHIVE_EXT or suffix.startswith(".part"):
        return "metadata_only", "", "Binary media or archive; bytes not semantically interpreted"
    if path.stat().st_size > MAX_TEXT_BYTES:
        return "metadata_only", "", "File larger than safe text extraction limit"
    try:
        if suffix in TEXT_EXT:
            content = path.read_text(encoding="utf-8", errors="replace")
            if suffix in (".html", ".htm"):
                parser = _HTMLText()
                parser.feed(content)
                content = "".join(parser.parts)
        elif suffix in (".docx", ".xlsx"):
            content = _from_office(path, suffix)
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return "extractor_unavailable", "", "Install pypdf locally to extract PDF text; OCR not attempted"
            reader = PdfReader(str(path))
            content = "\n".join(p.extract_text() or "" for p in reader.pages)
        else:
            return "metadata_only", "", "Unsupported file format"
        if not content.strip():
            return "metadata_only", "", "No extractable text"
        # Do not overfill private DB with massive unbounded exports.
        if len(content.encode("utf-8")) > MAX_EXTRACTED_BYTES:
            return "metadata_only", "", "Extracted text exceeds safe indexing limit"
        return "text_indexed", content, "Text extracted locally"
    except (OSError, UnicodeError, ET.ParseError, BadZipFile, ValueError, KeyError) as exc:
        return "extract_error", "", type(exc).__name__


def scan_sources(source_root: Path, db_path: Path = DEFAULT_DB) -> dict:
    root = source_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Source root must be an existing directory")
    target = _safe_db(db_path)
    if root == target or target in root.parents:
        raise ValueError("Invalid source and output paths")
    counts: Counter = Counter()
    db = _connect(target)
    try:
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            if ".git" in path.relative_to(root).parts:
                continue
            rel = path.relative_to(root).as_posix()
            if target == path.resolve():
                continue
            try:
                st = path.stat()
                if BLOCKED.search(rel):
                    status, content, detail = "blocked", "", "Potential clinical or credential source"
                else:
                    status, content, detail = _extract(path)
                digest = _hash_file(path, MAX_HASH_BYTES) if status != "blocked" else None
            except OSError as exc:
                st = path.stat()
                status, content, detail, digest = "extract_error", "", type(exc).__name__, None
            now = datetime.now(timezone.utc).isoformat()
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)",
                    (rel, st.st_size, digest, path.suffix.lower(), status, detail, now),
                )
                db.execute("DELETE FROM source_text WHERE relpath=?", (rel,))
                if status == "text_indexed":
                    db.execute("INSERT INTO source_text VALUES (?,?)", (rel, content))
            counts[status] += 1
    finally:
        db.close()
    return {"files_seen": sum(counts.values()), "status": dict(counts),
            "local_only": True, "read_only_sources": True}


def _no_secrets(value, parent_key=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if SECRET_KEY.search(k):
                raise ValueError("Credentials or full account identifiers are forbidden in finance snapshots")
            _no_secrets(v, k)
    elif isinstance(value, list):
        for v in value:
            _no_secrets(v, parent_key)


def _money(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Non-numeric financial value") from exc
    if not n.is_finite() or abs(n) > Decimal("1000000000000"):
        raise ValueError("Nonfinite or unreasonable financial value")
    return str(n)


def _s(value, *, max_length=240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > max_length:
        raise ValueError("Field too long")
    return text


def ingest_finances(finance_json: Path, db_path: Path = DEFAULT_DB) -> dict:
    """Import an *owner-exported* JSON snapshot; never connect to a financial API."""
    raw = finance_json.read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Finance JSON exceeds 64 MB cap")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Finance snapshot must be an object")
    _no_secrets(payload)
    allowed = {"source", "captured_at", "accounts", "holdings", "transactions", "recurring", "coverage"}
    if set(payload) - allowed:
        raise ValueError("Unexpected finance snapshot keys")
    if payload.get("source") != "OWNER_EXPORTED_READ_ONLY":
        raise ValueError("Snapshot must clearly identify owner-exported data")
    captured = _s(payload.get("captured_at"), max_length=50)
    if not captured:
        raise ValueError("Missing captured_at; live/current is never assumed")
    db = _connect(db_path)
    counts = {}
    try:
        specs = [
            ("accounts", "finance_accounts", ("source_id", "institution", "name", "account_type", "balance_usd", "available_usd", "balance_date", "captured_at")),
            ("holdings", "finance_holdings", ("holding_id", "account_ref", "security", "ticker", "quantity", "value_usd", "price_date", "captured_at")),
            ("transactions", "finance_transactions", ("source_id", "account_ref", "txn_date", "description", "signed_amount", "category", "pending", "captured_at")),
            ("recurring", "finance_recurring", ("source_id", "description", "frequency", "amount_usd", "next_date", "captured_at")),
        ]
        staged = []
        for kind, table, columns in specs:
            rows = payload.get(kind, [])
            if not isinstance(rows, list):
                raise ValueError(f"{kind} must be a list")
            values = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"Invalid {kind} row")
                if kind == "accounts":
                    v = (_s(row.get("id")), _s(row.get("institution")), _s(row.get("name")),
                         _s(row.get("type")), _money(row.get("balance_usd")),
                         _money(row.get("available_usd")), _s(row.get("balance_date")), captured)
                elif kind == "holdings":
                    v = (_s(row.get("id")), _s(row.get("account_ref")), _s(row.get("security")),
                         _s(row.get("ticker")), _money(row.get("quantity")), _money(row.get("value_usd")),
                         _s(row.get("price_date")), captured)
                elif kind == "transactions":
                    pending = row.get("pending", False)
                    if not isinstance(pending, bool):
                        raise ValueError("pending must be boolean")
                    v = (_s(row.get("id")), _s(row.get("account_ref")), _s(row.get("date")),
                         _s(row.get("description")), _money(row.get("signed_amount")),
                         _s(row.get("category")), int(pending), captured)
                else:
                    v = (_s(row.get("id")), _s(row.get("description")), _s(row.get("frequency")),
                         _money(row.get("amount_usd")), _s(row.get("next_date")), captured)
                if not v[0]:
                    raise ValueError(f"Every {kind} row requires a stable id")
                values.append(v)
            staged.append((table, columns, values))
            counts[kind] = len(values)
        with db:
            for table, cols, values in staged:
                cols_sql = ",".join(cols)
                slots = ",".join("?" for _ in cols)
                db.executemany(f"INSERT OR REPLACE INTO {table} ({cols_sql}) VALUES ({slots})", values)
    finally:
        db.close()
    return {"imported": counts, "captured_at": captured,
            "sync": "MANUAL_SNAPSHOT_ONLY", "read_only": True}


def report(db_path: Path = DEFAULT_DB) -> dict:
    db = _connect(db_path)
    try:
        statuses = db.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()
        tables = ("finance_accounts", "finance_holdings", "finance_transactions", "finance_recurring")
        return {"files": dict(statuses),
                "finance": {t.removeprefix("finance_"): db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables},
                "private_local_store": str(_safe_db(db_path))}
    finally:
        db.close()


def find_text(query: str, db_path: Path = DEFAULT_DB, limit: int = 20) -> list[dict]:
    if not query.strip() or len(query) > 120:
        raise ValueError("Enter a search term of 1 to 120 characters")
    # Bound output and escape LIKE wildcards. No model instructions are executed.
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    db = _connect(db_path)
    try:
        rows = db.execute(
            "SELECT relpath, substr(content,1,400) FROM source_text "
            "WHERE content LIKE ? ESCAPE '\\' ORDER BY relpath LIMIT ?",
            (pattern, max(1, min(limit, 50))),
        ).fetchall()
        return [{"file": p, "preview": v} for p, v in rows]
    finally:
        db.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline read-only Know Me and finances importer")
    p.add_argument("--source-root", type=Path, help="Local folder containing files exported from Know Me")
    p.add_argument("--finances", type=Path, help="Owner-exported read-only finance snapshot JSON")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Private DB outside repo")
    p.add_argument("--search", help="Search indexed local text")
    args = p.parse_args(argv)
    if not (args.source_root or args.finances or args.search):
        result = report(args.db)
    else:
        result = {}
        if args.source_root:
            result["sources"] = scan_sources(args.source_root, args.db)
        if args.finances:
            result["finances"] = ingest_finances(args.finances, args.db)
        if args.search:
            result["matches"] = find_text(args.search, args.db)
        result["summary"] = report(args.db)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
