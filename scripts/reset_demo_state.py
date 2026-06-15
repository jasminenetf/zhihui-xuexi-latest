#!/usr/bin/env python3
"""Clean QA/demo pollution without touching secrets or the built-in high-math course."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DB_PATHS = [ROOT / "data" / "app.db", ROOT / "backend" / "data" / "app.db"]
TEST_MARKERS = ("QA_TEST_", "P0_SMOKE_", "TEMP_QA_", "P0 Smoke", "verify_", "test")
KEEP_COURSE_NAMES = {"高等数学上册"}


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _has_table(con, table):
        return set()
    return {row[1] for row in con.execute(f"pragma table_info({table})")}


def _contains_marker(*values: object) -> bool:
    text = " ".join(str(v or "") for v in values)
    return any(marker.lower() in text.lower() for marker in TEST_MARKERS)


def _fetch_dicts(con: sqlite3.Connection, sql: str, params: Iterable[object] = ()) -> list[dict]:
    con.row_factory = sqlite3.Row
    return [dict(row) for row in con.execute(sql, tuple(params)).fetchall()]


def _select_pollution(con: sqlite3.Connection) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {"courses": [], "sessions": [], "quiz_attempts": [], "mastery": [], "resources": [], "users": []}

    if _has_table(con, "courses"):
        courses = _fetch_dicts(con, "select id,name,description from courses order by id")
        result["courses"] = [
            c for c in courses
            if c.get("name") not in KEEP_COURSE_NAMES
            and (
                _contains_marker(c.get("name"), c.get("description"))
                or (str(c.get("name") or "").strip().lower() == "x" and str(c.get("description") or "").strip().lower() == "y")
                or "测试课程" in str(c.get("name") or "") + str(c.get("description") or "")
            )
        ]

    if _has_table(con, "learning_sessions"):
        sessions = _fetch_dicts(con, "select id,title,topic,message_count,summary from learning_sessions order by id")
        seen_empty: set[tuple[str, str]] = set()
        for s in sessions:
            title = str(s.get("title") or "")
            topic = str(s.get("topic") or "")
            key = (title, topic)
            is_empty_duplicate = int(s.get("message_count") or 0) == 0 and key in seen_empty and title in {"函数极限", "定积分"}
            if int(s.get("message_count") or 0) == 0:
                seen_empty.add(key)
            if _contains_marker(title, topic, s.get("summary")) or is_empty_duplicate:
                result["sessions"].append(s)

    if _has_table(con, "quiz_attempts"):
        cols = _columns(con, "quiz_attempts")
        select_cols = [c for c in ["id", "topic", "knowledge_point", "question_text", "explanation"] if c in cols]
        attempts = _fetch_dicts(con, "select " + ",".join(select_cols) + " from quiz_attempts order by id")
        result["quiz_attempts"] = [a for a in attempts if _contains_marker(*a.values())]

    if _has_table(con, "knowledge_mastery"):
        cols = _columns(con, "knowledge_mastery")
        if "knowledge_point" in cols:
            result["mastery"] = _fetch_dicts(
                con,
                "select id,knowledge_point,mastery_score from knowledge_mastery where "
                + " or ".join(["lower(knowledge_point) like ?" for _ in TEST_MARKERS]),
                [f"%{m.lower()}%" for m in TEST_MARKERS],
            )

    if _has_table(con, "resource_artifacts"):
        cols = _columns(con, "resource_artifacts")
        select_cols = [c for c in ["id", "artifact_id", "job_id", "topic", "title", "resource_type"] if c in cols]
        resources = _fetch_dicts(con, "select " + ",".join(select_cols) + " from resource_artifacts order by id")
        result["resources"] = [r for r in resources if _contains_marker(*r.values())]

    if _has_table(con, "users"):
        users = _fetch_dicts(con, "select id,username from users order by id")
        result["users"] = [u for u in users if _contains_marker(u.get("username"))]

    return result


def _delete_ids(con: sqlite3.Connection, table: str, ids: list[int]) -> int:
    if not ids or not _has_table(con, table):
        return 0
    marks = ",".join("?" for _ in ids)
    con.execute(f"delete from {table} where id in ({marks})", ids)
    return len(ids)


def _apply_cleanup(con: sqlite3.Connection, selected: dict[str, list[dict]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    course_ids = [int(x["id"]) for x in selected["courses"]]
    session_ids = [int(x["id"]) for x in selected["sessions"]]
    quiz_ids = [int(x["id"]) for x in selected["quiz_attempts"]]
    mastery_ids = [int(x["id"]) for x in selected["mastery"]]
    resource_ids = [int(x["id"]) for x in selected["resources"]]
    user_ids = [int(x["id"]) for x in selected["users"]]

    con.execute("pragma foreign_keys=off")
    if course_ids:
        for table in ("knowledge_chunks", "course_files", "learning_progress", "learning_sessions", "quiz_attempts", "knowledge_mastery", "resource_artifacts", "resource_jobs"):
            if _has_table(con, table) and "course_id" in _columns(con, table):
                marks = ",".join("?" for _ in course_ids)
                cur = con.execute(f"delete from {table} where course_id in ({marks})", course_ids)
                counts[table] = counts.get(table, 0) + cur.rowcount
    if session_ids:
        if _has_table(con, "chat_messages"):
            marks = ",".join("?" for _ in session_ids)
            counts["chat_messages"] = con.execute(f"delete from chat_messages where session_id in ({marks})", session_ids).rowcount
        counts["learning_sessions"] = counts.get("learning_sessions", 0) + _delete_ids(con, "learning_sessions", session_ids)
    counts["quiz_attempts"] = counts.get("quiz_attempts", 0) + _delete_ids(con, "quiz_attempts", quiz_ids)
    counts["knowledge_mastery"] = counts.get("knowledge_mastery", 0) + _delete_ids(con, "knowledge_mastery", mastery_ids)
    counts["resource_artifacts"] = counts.get("resource_artifacts", 0) + _delete_ids(con, "resource_artifacts", resource_ids)
    counts["courses"] = counts.get("courses", 0) + _delete_ids(con, "courses", course_ids)
    counts["users"] = counts.get("users", 0) + _delete_ids(con, "users", user_ids)
    con.commit()
    return {k: v for k, v in counts.items() if v}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset QA pollution from demo SQLite databases.")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be deleted.")
    parser.add_argument("--apply", action="store_true", help="Apply cleanup.")
    args = parser.parse_args()
    if args.apply == args.dry_run:
        parser.error("choose exactly one of --dry-run or --apply")

    print("=== Demo State Reset ===")
    print("保留：内置《高等数学上册》、正常函数极限/定积分/导数/连续演示资源、backend/.env")
    any_db = False
    for db in DB_PATHS:
        if not db.exists():
            continue
        any_db = True
        con = sqlite3.connect(db)
        selected = _select_pollution(con)
        print(f"\nDB: {db.relative_to(ROOT)}")
        for key, rows in selected.items():
            label = {
                "courses": "将删除课程",
                "sessions": "将删除会话",
                "quiz_attempts": "将删除错题/答题",
                "mastery": "将删除测试掌握度",
                "resources": "将删除测试资源",
                "users": "将删除测试用户",
            }[key]
            print(f"{label}: {len(rows)}")
            for row in rows[:12]:
                summary = row.get("name") or row.get("title") or row.get("knowledge_point") or row.get("topic") or row.get("username") or row.get("artifact_id") or row.get("id")
                print(f"  - id={row.get('id')} {summary}")
            if len(rows) > 12:
                print(f"  ... 还有 {len(rows) - 12} 条")
        if args.apply:
            counts = _apply_cleanup(con, selected)
            print("已执行清理：" + (", ".join(f"{k}={v}" for k, v in counts.items()) if counts else "无可清理项"))
        else:
            print("dry-run：未删除任何数据")
        con.close()
    if not any_db:
        print("未找到 SQLite 数据库，未执行任何操作")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
