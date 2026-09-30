# -*- coding: utf-8 -*-
"""発送予定日の判定（要件定義書 BR-23）。

★このモジュールは repository も external も import しない（設計 2.2）。
  「いまの日時」も引数で受け取る。★`date.today()` を中で呼ぶと、
  日付が変わった瞬間に落ちる試験ができあがって、誰も直せなくなる。

BR-23
    出荷指示は、出荷元拠点の締め時刻（初期値15時）までに出たものは当日、
    それ以降は翌営業日に発送する。
    営業日は「営業する曜日の集合」と「休業日の一覧」で表す。
    非営業日が続く場合は、次に営業する日に発送する。
    ★発送予定日は出荷指示の作成時に出荷単位で確定して保存し、
      以後に拠点の営業日設定を変更しても再計算しない。

★「保存したものを再計算しない」はここでは守れない（保存が絡むため）。
  それはシステムテスト ST-413 の担当。ここが守るのは「1回目にどう決めるか」だけ。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# 営業曜日のビット位置。★DDL の location.business_days と同じ並び（日=bit0 〜 土=bit6）
SUNDAY_BIT = 0
# 休業日が延々と続く設定を渡されても止まるようにする（UT-407）
MAX_LOOKAHEAD_DAYS = 366


@dataclass(frozen=True)
class LocationCalendar:
    """拠点の営業日設定。★DBから読んだ値を、そのままの形で受け取る。"""

    # 営業する曜日。0=日 〜 6=土。DDL の TINYINT のビットは from_bitmask() で開く
    business_weekdays: frozenset[int]
    cutoff: time
    # その拠点だけの休業日（E-… location_holiday）
    holidays: frozenset[date] = frozenset()

    @staticmethod
    def from_bitmask(mask: int, cutoff: time, holidays: frozenset[date] = frozenset()
                     ) -> "LocationCalendar":
        """location.business_days（日=bit0 〜 土=bit6）を開く。"""
        days = frozenset(i for i in range(7) if mask & (1 << (SUNDAY_BIT + i)))
        return LocationCalendar(business_weekdays=days, cutoff=cutoff, holidays=holidays)


def _sunday_based_weekday(d: date) -> int:
    """Python は月曜=0。★DDL のビットは日曜=0 なので、ここで合わせる。"""
    return (d.weekday() + 1) % 7


def is_business_day(d: date, cal: LocationCalendar) -> bool:
    return _sunday_based_weekday(d) in cal.business_weekdays and d not in cal.holidays


def next_business_day(start: date, cal: LocationCalendar) -> date | None:
    """start を含めて、次に営業する日。

    ★見つからなければ None を返す。例外にしない（UT-407）。
      営業する曜日が1つも無い拠点は「設定が間違っている」のであって、
      出荷指示そのものが失敗すべき異常ではない。呼び出し側が判断する。
    """
    if not cal.business_weekdays:
        return None
    d = start
    for _ in range(MAX_LOOKAHEAD_DAYS):
        if is_business_day(d, cal):
            return d
        d += timedelta(days=1)
    return None


def planned_ship_date(instructed_at: datetime, cal: LocationCalendar) -> date | None:
    """BR-23。出荷指示を出した日時から、発送予定日を決める。

    ★締め時刻「ちょうど」は当日に入れる（UT-401）。
      「15時まで」と書いてあるので 15:00:00 は含む。1秒でも過ぎたら翌営業日（UT-402）。
    """
    same_day = instructed_at.time() <= cal.cutoff
    start = instructed_at.date() if same_day else instructed_at.date() + timedelta(days=1)
    return next_business_day(start, cal)
