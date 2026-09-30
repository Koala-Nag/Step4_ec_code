# -*- coding: utf-8 -*-
"""起動時の移行（設計 2.2.1）。

★なぜ起動時なのか。**Week10 で閉域化すると、シェルから叩ける口が無くなる**（9.8.3）。
  そのときアプリは「何を流すか」を自分で決める必要があり、台帳が無いと決められない。

★複数インスタンスが同時に起動する。ここがこの仕組みの本体。

    ① GET_LOCK('ec_koala_migrate', 60) で排他する。取れなければ起動を失敗させる
       （App Service が再起動して拾い直す）
    ② ★ロックを取ってから、台帳をもう一度読む
       先に取ったインスタンスが流し終えている場合があり、
       待っている間に「未適用」でなくなる
    ③ 未適用の番号だけを、番号順に流す
    ④ 1本流すごとに台帳へ1行書く。流し終えてから RELEASE_LOCK

★②が要る理由は、引当（6.2.1）とまったく同じ。
  「読んでから書くまでの隙間」に、他が同じことをする。
  引当は条件付きUPDATEの更新件数で判定し、ここはロックを取ってから読み直すことで判定する。
  ★これを落とすと、後発が同じ ALTER を投げて ERROR 1060／1061 で起動に失敗する
    （R-06 で実機再現している）。

★batch_lock（6.6.1）は使わない。
  移行が走るのは「表がまだ揃っていないかもしれない時点」であり、
  移行のロックを移行対象の表に置くと、初回構築で鶏と卵になる。
  GET_LOCK は MySQL 組み込みで表に依存せず、★接続が切れると自動で解放されるので、
  落ちたプロセスのロックも残らない。
"""
from __future__ import annotations

import pathlib
import re

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core import applog

LOCK_NAME = "ec_koala_migrate"   # ★共有サーバではロック名もサーバ全体で共有される（R-35）
LOCK_TIMEOUT_SECONDS = 60

# migrations/001_xxx.sql の「001」を取る
_NUM = re.compile(r"^(\d{3})_.*\.sql$")

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "migrations"


class MigrationError(RuntimeError):
    """移行に失敗した。★起動を止める（中途半端な状態で受け付けない）。"""


def available(directory: pathlib.Path | None = None) -> list[tuple[str, pathlib.Path]]:
    """migrations/ にある番号とファイル。★番号順。"""
    d = directory or MIGRATIONS_DIR
    if not d.exists():
        return []
    out: list[tuple[str, pathlib.Path]] = []
    for f in sorted(d.iterdir()):
        m = _NUM.match(f.name)
        if m:
            out.append((m.group(1), f))
    return out


def applied(conn) -> set[str]:
    """台帳にある番号。★表がまだ無い場合は空（初回構築）。"""
    row = conn.execute(
        text("SELECT COUNT(*) c FROM information_schema.tables "
             " WHERE table_schema = DATABASE() AND table_name = 'schema_migration'")
    ).first()
    if not row or int(row.c) == 0:
        return set()
    return {r.version for r in conn.execute(text("SELECT version FROM schema_migration"))}


def split_statements(sql: str) -> list[str]:
    """`.sql` を文に割る。

    ★DBAPI は複数文を1回で送れない。区切って1本ずつ送る。
    ★行コメント（-- ）を落としてから割る。
      コメントの中の `;` で割ってしまうと、文が壊れる。
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def _apply_one(conn, version: str, path: pathlib.Path) -> int:
    """1本流して、台帳に1行書く。★同じトランザクションにはできない。

    ★MySQL の DDL は暗黙にコミットする。だから「流したのに台帳に無い」瞬間が必ずある。
      そこで落ちたら、次の起動でもう一度流れる——★だから移行は冪等に書く
      （`CREATE TABLE IF NOT EXISTS`・`INSERT IGNORE`）。
      ★列を足す ALTER は冪等にできないので、そこは 2.2.1 の台帳で防ぐ。
    """
    sql = path.read_text(encoding="utf-8")
    n = 0
    for stmt in split_statements(sql):
        # ★USE と SET NAMES は接続側で済んでいる。ここでは流さない
        #   （USE を流すと SQLAlchemy の接続先が変わる）
        low = stmt.lower()
        if low.startswith("use ") or low.startswith("set names"):
            continue
        conn.execute(text(stmt))
        n += 1
    conn.execute(
        text("INSERT IGNORE INTO schema_migration (version, note) VALUES (:v, :n)"),
        {"v": version, "n": "起動時の移行で適用（2.2.1）"},
    )
    return n


def run(engine: Engine, *, directory: pathlib.Path | None = None) -> dict:
    """起動時に1回呼ぶ。戻り値は何をしたか（ログと試験のため）。"""
    result: dict = {"locked": False, "applied": [], "skipped": [], "statements": 0}

    # ★1つの接続の中でやりきる。GET_LOCK は接続に紐づくので、
    #   別の接続で RELEASE_LOCK しても解放されない
    with engine.connect() as conn:
        got = conn.execute(
            text("SELECT GET_LOCK(:n, :t) AS g"),
            {"n": LOCK_NAME, "t": LOCK_TIMEOUT_SECONDS},
        ).scalar()
        if got != 1:
            # ★取れなければ起動を失敗させる（2.2.1 ①）。
            #   待ち続けると、壊れた1インスタンスのせいで全部が起動しなくなる
            raise MigrationError(f"移行のロックが取れない（{LOCK_TIMEOUT_SECONDS}秒）")
        result["locked"] = True

        try:
            # ★② ロックを取ってから読み直す。ここがこの仕組みの肝
            done = applied(conn)
            todo = [(v, p) for v, p in available(directory) if v not in done]
            result["skipped"] = sorted(done)

            for version, path in todo:
                try:
                    result["statements"] += _apply_one(conn, version, path)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    # ★途中で落ちたら、そこで止める。後ろを流さない。
                    #   次の起動は、成功したぶんを台帳で飛ばして続きから（IT-416）
                    raise MigrationError(f"{path.name} で失敗: {type(e).__name__}") from e
                result["applied"].append(version)
        finally:
            conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})
            conn.commit()

    applog.emit("migrate.done", count=len(result["applied"]))
    return result
