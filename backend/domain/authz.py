# -*- coding: utf-8 -*-
"""権限の判定（要件定義書 2.4 の権限表・設計 4.1.2・N-28・N-28a）。

★このモジュールは repository も external も import しない（設計 2.2）。
  権限表は「どの役割がどの機能をどこまでできるか」の表でしかないので、
  DBを立てずに全通り確かめられる。★人数分の組み合わせを目で追わずに済む。

★2.4 が正。ここはその写しであって、判断を足していない。
  食い違いを見つけたら 2.4 を直して、ここを合わせる。

★「画面がボタンを隠すか」とは無関係（4.1.2）。
  APIが自分で判定する。隠すのは親切であって、権限ではない（SEC-703）。
"""
from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    """operator.role。DDL のコメントと同じ並び。"""

    ADMIN = 1       # 運用管理者
    ORDER = 2       # 受注担当
    WAREHOUSE = 3   # 倉庫スタッフ（拠点で共有）
    STORE = 4       # 店舗スタッフ（拠点で共有）
    SUPPORT = 5     # サポート


class Perm(IntEnum):
    """2.4 の表記そのまま。★数の大小に意味を持たせない（NONE が0なだけ）。"""

    NONE = 0        # —      実行できない
    READ = 1        # 参照   見ることだけ
    OWN_SITE = 2    # 自拠点 自分の拠点の分だけ
    FULL = 3        # 可     実行できる


_ = Perm
# 2.4 の権限表。★キーは機能ID（F-xxx）。APIのIDにしないのは、
#   1つのAPIが複数の機能を持つことがあるため（2.4 が「権限は機能単位」と決めている）
TABLE: dict[str, dict[Role, Perm]] = {
    # 会員
    "F-609": {Role.ADMIN: _.READ, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    # 商品・マスタ
    "F-701": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    # ★2.4 は「F-701〜708」を1行で決めている。機能ごとに引けるよう同じ権限で並べる
    "F-702": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-703": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-704": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-705": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-709": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    # 在庫
    "F-801": {Role.ADMIN: _.READ, Role.ORDER: _.READ, Role.WAREHOUSE: _.OWN_SITE,
              Role.STORE: _.OWN_SITE, Role.SUPPORT: _.NONE},
    "F-802": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.OWN_SITE,
              Role.STORE: _.OWN_SITE, Role.SUPPORT: _.NONE},
    # 出荷
    # ★店頭への払い出しは店舗だけが書く。運用管理者は参照、倉庫は —（2.4）
    # ★EC販売可否（商品×拠点の除外）は運用管理者だけ。滞留在庫の抽出は受注担当も参照できる（2.4）
    "F-806": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-807": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-808": {Role.ADMIN: _.READ, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.OWN_SITE, Role.SUPPORT: _.NONE},
    "F-809": {Role.ADMIN: _.FULL, Role.ORDER: _.READ, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-1302": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
               Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-805": {Role.ADMIN: _.READ, Role.ORDER: _.READ, Role.WAREHOUSE: _.OWN_SITE,
              Role.STORE: _.OWN_SITE, Role.SUPPORT: _.NONE},
    # 販売設定（R-33）。★運用管理者だけ（2.4 F-308）
    "F-308": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    # クーポン管理（R-32）。★運用管理者だけ（2.4）
    "F-1001": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
               Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    # 返品（R-31）。★2.4 の行そのまま。近い機能の行で代用しない（10.2.11c）
    # ★倉庫は「自拠点」＝返送先の倉庫（BR-19）。店舗は返品に一切触らない（店舗から出荷したものも倉庫に戻る）
    "F-507": {Role.ADMIN: _.READ, Role.ORDER: _.READ, Role.WAREHOUSE: _.OWN_SITE,
              Role.STORE: _.NONE, Role.SUPPORT: _.FULL},
    "F-503a": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
               Role.STORE: _.NONE, Role.SUPPORT: _.FULL},
    "F-503b": {Role.ADMIN: _.READ, Role.ORDER: _.NONE, Role.WAREHOUSE: _.OWN_SITE,
               Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-503c": {Role.ADMIN: _.READ, Role.ORDER: _.NONE, Role.WAREHOUSE: _.OWN_SITE,
               Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-503d": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.NONE,
               Role.STORE: _.NONE, Role.SUPPORT: _.FULL},
    "F-503e": {Role.ADMIN: _.FULL, Role.ORDER: _.NONE, Role.WAREHOUSE: _.READ,
               Role.STORE: _.NONE, Role.SUPPORT: _.FULL},
    "F-504": {Role.ADMIN: _.READ, Role.ORDER: _.NONE, Role.WAREHOUSE: _.OWN_SITE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    # 注文
    "F-901": {Role.ADMIN: _.READ, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.READ},
    "F-903a": {Role.ADMIN: _.FULL, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
               Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    # ★対応メモは、受注担当だけでなく運用管理者とサポートも書く（2.4。問い合わせに答えた記録を残す）
    "F-908": {Role.ADMIN: _.FULL, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.FULL},
    "F-904": {Role.ADMIN: _.FULL, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-911": {Role.ADMIN: _.FULL, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
    "F-912": {Role.ADMIN: _.FULL, Role.ORDER: _.FULL, Role.WAREHOUSE: _.NONE,
              Role.STORE: _.NONE, Role.SUPPORT: _.NONE},
}


def permission(role: Role, feature: str) -> Perm:
    return TABLE.get(feature, {}).get(role, Perm.NONE)


def can_read(role: Role, feature: str) -> bool:
    return permission(role, feature) != Perm.NONE


def can_write(role: Role, feature: str) -> bool:
    """更新できるか。★「参照」は書けない。ここを緩めると SEC-703 が通る。"""
    return permission(role, feature) in (Perm.FULL, Perm.OWN_SITE)


def is_site_scoped(role: Role, feature: str) -> bool:
    """自拠点のみか。★真なら、拠点を引数で受け取ってはいけない（N-28a・SEC-701）。

    ★「渡された拠点が自分のものか確かめる」ではなく「そもそも受け取らない」。
      確かめる形だと、確かめ忘れた1本のAPIから全部漏れる。
    """
    return permission(role, feature) == Perm.OWN_SITE


def effective_location(role: Role, feature: str, own_location: str | None,
                       asked_location: str | None) -> str | None:
    """実際に見せてよい拠点を決める（N-28a）。

    戻り値
        文字列  その拠点だけに絞る
        None    絞らない（全拠点を見てよい）
    例外
        ValueError  自拠点のみの役割が、他拠点を指定してきた（→ ERR-1106）
    """
    if not is_site_scoped(role, feature):
        return asked_location            # 絞らない役割は、指定があればそれに従う
    if asked_location is not None and asked_location != own_location:
        raise ValueError("ERR-1106")
    # ★指定を無視して自拠点で上書きする。指定が無くても自拠点に絞る
    return own_location
