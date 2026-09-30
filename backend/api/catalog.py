# -*- coding: utf-8 -*-
"""運営が入力する画面の API（R-27）。

  AP-B34  運営者の管理            F-1302
  AP-B03  マスタの登録・編集      F-709
  AP-B02  商品・SKU・価格・画像・公開  F-701〜705
  AP-B08  店頭への払い出し        F-808
  AP-B04  拠点（参照だけ。選択肢に使う）F-809

★権限は要件 2.4 の表そのまま（domain/authz.py）。APIが自分で判定する（4.1.2）。
★F-808 は店舗の「自拠点」。★拠点を引数で受け取らない（N-28a）——ログインした拠点で決める。
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime as _dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, StrictBool, StrictInt, StrictStr
from sqlalchemy.orm import Session

from core import applog, security
from core.db import get_db
from core.deps import current_operator, require_internal_auth
from core.errors import AppError
from domain import authz, catalog as cg, password as pw
from domain.authz import Role
from external import image_store
from repository import catalog as repo

router = APIRouter(prefix="/admin", tags=["admin-catalog"],
                   dependencies=[Depends(require_internal_auth)])


def _guard(operator: dict, feature: str, *, write: bool) -> Role:
    role = Role(int(operator["role"]))
    ok = authz.can_write(role, feature) if write else authz.can_read(role, feature)
    if not ok:
        raise AppError("ERR-1102", {"feature": feature})
    return role


def _field_error(reason: str) -> AppError:
    """domain の理由符号（"price:range" など）を 8.2 のコードに寄せる。"""
    field, _, why = reason.partition(":")
    code = {"empty": "ERR-1001", "required": "ERR-1001", "choice": "ERR-1004",
            "kind_mismatch": "ERR-1004", "not_allowed": "ERR-1004",
            "format": "ERR-1002"}.get(why, "ERR-1003")
    return AppError(code, {"field": field, "reason": why})


# ============================================================
# AP-B04  拠点（参照）
# ============================================================
@router.get("/locations")
def list_locations(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    # ★運営者の登録（F-1302）と在庫の入力（F-702）の選択肢に使う
    role = Role(int(operator["role"]))
    if not (authz.can_read(role, "F-809") or authz.can_write(role, "F-1302")
            or authz.can_write(role, "F-701")):
        raise AppError("ERR-1102", {"feature": "F-809"})
    return {"data": {"locations": repo.locations(db), "prefectures": repo.prefectures(db),
                     "can_edit": authz.can_write(role, "F-809")}}


# ============================================================
# AP-B34  運営者（F-1302）
# ============================================================
class OperatorCreate(BaseModel):
    operator_id: StrictStr
    name: StrictStr
    email: EmailStr
    password: StrictStr
    role: StrictInt
    location_code: StrictStr | None = None


class OperatorPatch(BaseModel):
    name: StrictStr | None = None
    role: StrictInt | None = None
    location_code: StrictStr | None = None
    clear_location: StrictBool = False
    is_active: StrictBool | None = None
    password: StrictStr | None = None


@router.get("/operators")
def list_operators(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-1302", write=False)
    return {"data": {"operators": repo.list_operators(db)}}


@router.post("/operators")
def create_operator(body: OperatorCreate, db: Session = Depends(get_db),
                    operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-1302", write=True)
    oid = body.operator_id.strip().upper()
    if not cg.OPERATOR_ID_RE.match(oid):
        raise AppError("ERR-1002", {"field": "operator_id"})
    if not body.name.strip():
        raise AppError("ERR-1001", {"field": "name"})
    if len(body.name) > 50:
        raise AppError("ERR-1003", {"field": "name"})
    if (why := pw.policy_error(body.password)):
        raise AppError("ERR-1003", {"field": "password", "reason": why})
    loc = body.location_code or None
    if (why := cg.operator_location_error(body.role, loc, repo.location_kind(db, loc))):
        raise _field_error(why)
    try:
        repo.create_operator(db, operator_id=oid, name=body.name.strip(),
                             email=pw.normalize_email(str(body.email)),
                             password_hash=security.hash_password(body.password),
                             role=body.role, location_code=loc, by=operator["operator_id"])
    except repo.Duplicate:
        raise AppError("ERR-1216", {"field": "operator_id_or_email"})
    applog.emit("admin.operator_created")
    return {"data": {"operator_id": oid}}


@router.patch("/operators/{operator_id}")
def update_operator(operator_id: str, body: OperatorPatch, db: Session = Depends(get_db),
                    operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-1302", write=True)
    cur = repo.get_operator(db, operator_id)
    if not cur:
        raise AppError("ERR-1215")
    if operator_id == operator["operator_id"] and (body.is_active is False or body.role not in (None, 1)):
        # ★自分を無効にしたり、運用管理者から外したりしない（運営者の管理ができる人がいなくなる）
        raise AppError("ERR-1004", {"field": "operator_id", "reason": "self"})
    fields: dict = {}
    if body.name is not None:
        if not body.name.strip():
            raise AppError("ERR-1001", {"field": "name"})
        fields["name"] = body.name.strip()
    role = body.role if body.role is not None else int(cur["role"])
    loc = None if body.clear_location else (body.location_code or cur["location_code"])
    if body.role is not None or body.location_code is not None or body.clear_location:
        if (why := cg.operator_location_error(role, loc, repo.location_kind(db, loc))):
            raise _field_error(why)
        fields["role"] = role
        fields["location_code"] = loc
    if body.is_active is not None:
        fields["is_active"] = body.is_active
    if body.password is not None:
        if (why := pw.policy_error(body.password)):
            raise AppError("ERR-1003", {"field": "password", "reason": why})
        fields["password_hash"] = security.hash_password(body.password)
    if not fields:
        raise AppError("ERR-1001", {"field": "body"})
    repo.update_operator(db, operator_id, fields, by=operator["operator_id"])
    applog.emit("admin.operator_updated")
    return {"data": {"operator_id": operator_id, "updated": sorted(k for k in fields if k != "password_hash")}}


# ============================================================
# AP-B03  マスタ（F-709）
# ============================================================
class MasterCreate(BaseModel):
    code: StrictStr
    name: StrictStr
    sort_no: StrictInt | None = None
    parent_code: StrictStr | None = None


class MasterPatch(BaseModel):
    name: StrictStr | None = None
    sort_no: StrictInt | None = None
    is_active: StrictBool | None = None


class SizeMapBody(BaseModel):
    size_code: StrictStr
    common_size_code: StrictStr


def _kind(kind: str) -> cg.MasterKind:
    if kind not in cg.MASTERS:
        raise AppError("ERR-1215")
    return cg.MASTERS[kind]


@router.get("/masters/size-map")
def get_size_map(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-709", write=False)
    return {"data": {"size_map": repo.list_size_map(db)}}


@router.post("/masters/size-map")
def post_size_map(body: SizeMapBody, db: Session = Depends(get_db),
                  operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-709", write=True)
    if not repo.exists_active(db, "sizes", body.size_code) or \
            not repo.exists_active(db, "common-sizes", body.common_size_code):
        raise AppError("ERR-1004", {"field": "size_code"})
    try:
        repo.add_size_map(db, body.size_code, body.common_size_code, by=operator["operator_id"])
    except repo.Duplicate:
        raise AppError("ERR-1216", {"field": "size_code"})
    return {"data": {"added": True}}


@router.get("/masters/{kind}")
def get_master(kind: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    _kind(kind)
    # ★商品の登録（F-701。受注・サポートは参照）でも選択肢として読むので、F-701 の参照でも通す
    role = Role(int(operator["role"]))
    if not (authz.can_read(role, "F-709") or authz.can_read(role, "F-701")):
        raise AppError("ERR-1102", {"feature": "F-709"})
    return {"data": {"kind": kind, "items": repo.list_master(db, kind)}}


@router.post("/masters/{kind}")
def post_master(kind: str, body: MasterCreate, db: Session = Depends(get_db),
                operator=Depends(current_operator)) -> dict:
    m = _kind(kind)
    _guard(operator, "F-709", write=True)
    code = body.code.strip().upper()
    if not m.code_re.match(code):
        raise AppError("ERR-1002", {"field": "code"})
    if not body.name.strip():
        raise AppError("ERR-1001", {"field": "name"})
    if len(body.name) > (30 if m.table in ("color", "size", "common_size") else 50):
        raise AppError("ERR-1003", {"field": "name"})
    parent = body.parent_code or None
    if m.has_parent and parent and not repo.exists_active(db, "categories", parent):
        raise AppError("ERR-1004", {"field": "parent_code"})
    try:
        repo.create_master(db, kind, code=code, name=body.name.strip(), sort_no=body.sort_no,
                           parent_code=parent, by=operator["operator_id"])
    except repo.Duplicate:
        raise AppError("ERR-1216", {"field": "code"})
    return {"data": {"code": code}}


@router.patch("/masters/{kind}/{code}")
def patch_master(kind: str, code: str, body: MasterPatch, db: Session = Depends(get_db),
                 operator=Depends(current_operator)) -> dict:
    m = _kind(kind)
    _guard(operator, "F-709", write=True)
    fields: dict = {}
    if body.name is not None:
        if not body.name.strip():
            raise AppError("ERR-1001", {"field": "name"})
        fields["name"] = body.name.strip()
    if body.sort_no is not None and m.has_sort:
        fields["sort_no"] = body.sort_no
    if body.is_active is not None:
        fields["is_active"] = body.is_active
    if not fields:
        raise AppError("ERR-1001", {"field": "body"})
    if repo.update_master(db, kind, code, fields, by=operator["operator_id"]) == 0:
        raise AppError("ERR-1215")
    return {"data": {"code": code, "updated": sorted(fields)}}


@router.delete("/masters/{kind}/{code}")
def delete_master(kind: str, code: str, db: Session = Depends(get_db),
                  operator=Depends(current_operator)) -> dict:
    _kind(kind)
    _guard(operator, "F-709", write=True)
    try:
        n = repo.delete_master(db, kind, code, by=operator["operator_id"])
    except repo.InUse:
        # ★使われているマスタは削除できず、無効化のみ（F-709）
        raise AppError("ERR-1217", {"field": "code"})
    if n == 0:
        raise AppError("ERR-1215")
    return {"data": {"deleted": code}}


# ============================================================
# AP-B02  商品（F-701〜705）
# ============================================================
class ProductCreate(BaseModel):
    product_code: StrictStr
    name: StrictStr
    category_code: StrictStr
    item_type_code: StrictStr
    material: StrictStr | None = None
    description: StrictStr | None = None
    price: StrictInt


class ProductPatch(BaseModel):
    name: StrictStr | None = None
    category_code: StrictStr | None = None
    item_type_code: StrictStr | None = None
    material: StrictStr | None = None
    description: StrictStr | None = None
    price: StrictInt | None = None
    is_published: StrictBool | None = None


class StockInit(BaseModel):
    location_code: StrictStr
    qty: StrictInt


class SkuBulk(BaseModel):
    colors: list[StrictStr]
    sizes: list[StrictStr]
    stocks: list[StockInit] = []


class StockItem(BaseModel):
    sku_code: StrictStr
    location_code: StrictStr
    qty: StrictInt


class StockBulk(BaseModel):
    items: list[StockItem]


class ImageUpload(BaseModel):
    color_code: StrictStr
    content_base64: StrictStr


class ImageMove(BaseModel):
    direction: StrictStr


def _product_or_404(db: Session, code: str) -> dict:
    p = repo.get_product(db, code)
    if not p:
        raise AppError("ERR-1215")
    return p


@router.get("/products")
def list_products(db: Session = Depends(get_db), operator=Depends(current_operator),
                  keyword: str | None = None) -> dict:
    _guard(operator, "F-701", write=False)
    rows = repo.list_products(db, keyword)
    return {"data": {"products": [{**r, "updated_at": str(r["updated_at"])} for r in rows]}}


@router.get("/products/{code}")
def get_product(code: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-701", write=False)
    p = _product_or_404(db, code)
    return {"data": {
        "product": {**p, "created_at": str(p["created_at"]), "updated_at": str(p["updated_at"])},
        "skus": repo.skus_of(db, code),
        "stocks": repo.stocks_of(db, code),
        "images": repo.images_of(db, code),
        "can_edit": authz.can_write(role, "F-701"),
    }}


@router.post("/products")
def create_product(body: ProductCreate, db: Session = Depends(get_db),
                   operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-701", write=True)
    code = body.product_code.strip().upper()
    if not cg.CODE_RE.match(code):
        raise AppError("ERR-1002", {"field": "product_code"})
    if (why := cg.product_input_error(name=body.name, price=body.price, material=body.material,
                                      description=body.description)):
        raise _field_error(why)
    if not repo.exists_active(db, "categories", body.category_code):
        raise AppError("ERR-1004", {"field": "category_code"})
    if not repo.exists_active(db, "item-types", body.item_type_code):
        raise AppError("ERR-1004", {"field": "item_type_code"})
    try:
        repo.create_product(db, {"product_code": code, "name": body.name.strip(),
                                 "category_code": body.category_code,
                                 "item_type_code": body.item_type_code,
                                 "material": body.material or None,
                                 "description": body.description or None,
                                 "price": body.price}, by=operator["operator_id"])
    except repo.Duplicate:
        raise AppError("ERR-1216", {"field": "product_code"})
    applog.emit("admin.product_created")
    return {"data": {"product_code": code, "is_published": False}}


@router.patch("/products/{code}")
def patch_product(code: str, body: ProductPatch, db: Session = Depends(get_db),
                  operator=Depends(current_operator)) -> dict:
    """商品の編集（F-701）・価格（F-704）・公開状態（F-705）。

    ★非公開にしたら、客側の一覧・検索・詳細・カートのどれからも見えなくなる。
      条件は repository/product.py と repository/cart.py の is_published の1か所ずつ。
    """
    _guard(operator, "F-701", write=True)
    cur = _product_or_404(db, code)
    if (why := cg.product_input_error(name=body.name, price=body.price, material=body.material,
                                      description=body.description)):
        raise _field_error(why)
    fields: dict = {}
    for k in ("name", "material", "description", "price", "is_published"):
        v = getattr(body, k)
        if v is not None:
            fields[k] = v.strip() if isinstance(v, str) and k == "name" else v
    if body.category_code is not None:
        if not repo.exists_active(db, "categories", body.category_code):
            raise AppError("ERR-1004", {"field": "category_code"})
        fields["category_code"] = body.category_code
    if body.item_type_code is not None:
        if not repo.exists_active(db, "item-types", body.item_type_code):
            raise AppError("ERR-1004", {"field": "item_type_code"})
        fields["item_type_code"] = body.item_type_code
    if body.is_published and not repo.skus_of(db, code):
        # ★SKU の無い商品は公開しない（客が選べるサイズが1つも無い画面になる）
        raise AppError("ERR-1004", {"field": "is_published", "reason": "no_sku"})
    if not fields:
        raise AppError("ERR-1001", {"field": "body"})
    repo.update_product(db, code, fields, by=operator["operator_id"], before=cur)
    applog.emit("admin.product_updated")
    return {"data": {"product_code": code, "updated": sorted(fields)}}


@router.post("/products/{code}/skus")
def bulk_skus(code: str, body: SkuBulk, db: Session = Depends(get_db),
              operator=Depends(current_operator)) -> dict:
    """SKU の一括生成（F-702）。★すでにある組み合わせは作らない。"""
    _guard(operator, "F-702", write=True)
    _product_or_404(db, code)
    if not body.colors or not body.sizes:
        raise AppError("ERR-1001", {"field": "colors" if not body.colors else "sizes"})
    for c in body.colors:
        if not repo.exists_active(db, "colors", c):
            raise AppError("ERR-1004", {"field": "colors", "value": c})
    common: dict[str, str] = {}
    for s in body.sizes:
        if not repo.exists_active(db, "sizes", s):
            raise AppError("ERR-1004", {"field": "sizes", "value": s})
        cs = repo.common_size_for(db, s)
        if not cs:
            # ★共通サイズ（F-109 の絞り込み）に対応していないサイズでは作れない
            raise AppError("ERR-1004", {"field": "sizes", "value": s, "reason": "no_size_map"})
        common[s] = cs
    known = {l["location_code"] for l in repo.locations(db)}
    for st in body.stocks:
        if st.location_code not in known:
            raise AppError("ERR-1004", {"field": "stocks.location_code"})
        if not (0 <= st.qty <= 99999):
            raise AppError("ERR-1003", {"field": "stocks.qty"})
    existing = {(s["color_code"], s["size_code"]) for s in repo.skus_of(db, code)}
    made, skipped = cg.plan_skus(code, body.colors, body.sizes, existing)
    if made:
        try:
            repo.create_skus(db, code, made, common, [s.model_dump() for s in body.stocks],
                             by=operator["operator_id"])
        except repo.Duplicate:
            raise AppError("ERR-1216", {"field": "skus"})
    return {"data": {"created": [m.sku_code for m in made],
                     "skipped": [f"{code}-{c}-{s}" for c, s in skipped]}}


@router.put("/products/{code}/stocks")
def put_stocks(code: str, body: StockBulk, db: Session = Depends(get_db),
               operator=Depends(current_operator)) -> dict:
    """拠点ごとの在庫数（F-702）。★引当済数を下回る値にはしない（ERR-1208）。"""
    _guard(operator, "F-702", write=True)
    _product_or_404(db, code)
    mine = {s["sku_code"] for s in repo.skus_of(db, code)}
    known = {l["location_code"] for l in repo.locations(db)}
    for it in body.items:
        if it.sku_code not in mine:
            raise AppError("ERR-1004", {"field": "sku_code"})
        if it.location_code not in known:
            raise AppError("ERR-1004", {"field": "location_code"})
        if not (0 <= it.qty <= 99999):
            raise AppError("ERR-1003", {"field": "qty"})
    try:
        repo.set_stocks(db, code, [i.model_dump() for i in body.items], by=operator["operator_id"])
    except ValueError as e:
        raise AppError(str(e), {"field": "qty"})
    return {"data": {"updated": len(body.items)}}


@router.post("/products/{code}/images")
def upload_image(code: str, body: ImageUpload, db: Session = Depends(get_db),
                 operator=Depends(current_operator)) -> dict:
    """画像の取り込み（F-703・N-36）。★拡張子ではなく中身で判定する。"""
    _guard(operator, "F-703", write=True)
    _product_or_404(db, code)
    if not repo.exists_active(db, "colors", body.color_code):
        raise AppError("ERR-1004", {"field": "color_code"})
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise AppError("ERR-1002", {"field": "file"})
    if (why := cg.image_error(data, repo.image_count(db, code))):
        raise AppError("ERR-1003" if why in ("too_large", "too_many") else "ERR-1002",
                       {"field": "file", "reason": why})
    sort_no = repo.next_image_sort(db, code, body.color_code)
    # ★ファイル名は規約で決める（商品画像の仕様 1.2）。画面から来た名前は使わない
    rel = f"products/{code}_{body.color_code}_{sort_no}.{cg.image_kind(data)}"
    image_store.save(rel, data)
    repo.add_image(db, code, body.color_code, sort_no, rel, by=operator["operator_id"])
    applog.emit("admin.image_uploaded")
    return {"data": {"color_code": body.color_code, "sort_no": sort_no, "url": rel}}


@router.delete("/products/{code}/images/{color}/{sort_no}")
def delete_image(code: str, color: str, sort_no: int, db: Session = Depends(get_db),
                 operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-703", write=True)
    url = repo.delete_image(db, code, color, sort_no, by=operator["operator_id"])
    if url is None:
        raise AppError("ERR-1215")
    image_store.delete(url)
    return {"data": {"deleted": url}}


@router.post("/products/{code}/images/{color}/{sort_no}/move")
def move_image(code: str, color: str, sort_no: int, body: ImageMove, db: Session = Depends(get_db),
               operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-703", write=True)
    if body.direction not in ("up", "down"):
        raise AppError("ERR-1004", {"field": "direction"})
    moved = repo.move_image(db, code, color, sort_no, body.direction, by=operator["operator_id"])
    return {"data": {"moved": moved}}


# ============================================================
# AP-B08  店頭への払い出し（F-808）
# ============================================================
class FloorMove(BaseModel):
    sku_code: StrictStr
    qty: StrictInt
    staff_name: StrictStr        # ★店舗のアカウントは共有。誰がやったかは手入力（2.4）
    # ★location_code を持たせない（N-28a）


@router.get("/stocks/move-to-floor")
def floor_page(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-808", write=False)
    loc = authz.effective_location(role, "F-808", operator["location_code"], None)
    return {"data": {"scope": loc or "all", "can_move": authz.can_write(role, "F-808"),
                     "history": [{**h, "created_at": str(h["created_at"])}
                                 for h in repo.floor_history(db, loc)]}}


@router.post("/stocks/move-to-floor")
def move_to_floor(body: FloorMove, db: Session = Depends(get_db),
                  operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-808", write=True)       # ★運用管理者は「参照」なので 403
    loc = authz.effective_location(role, "F-808", operator["location_code"], None)
    if not loc:
        raise AppError("ERR-1106")
    if not body.staff_name.strip():
        raise AppError("ERR-1001", {"field": "staff_name"})
    cur = repo.backyard_of(db, body.sku_code, loc)
    if cur is None:
        raise AppError("ERR-1004", {"field": "sku_code"})
    if (why := cg.floor_move_error(qty=body.qty, backyard_qty=int(cur["qty"]),
                                   reserved_qty=int(cur["reserved_qty"]))):
        raise AppError("ERR-1003", {"field": "qty", "reason": why.split(":")[1],
                                    "max_qty": max(int(cur["qty"]) - int(cur["reserved_qty"]), 0)})
    res = repo.move_to_floor(db, sku_code=body.sku_code, location_code=loc, qty=body.qty,
                             staff_name=body.staff_name.strip(), operator_id=operator["operator_id"])
    if res is None:
        # ★読んでから書くまでに引当が入った（条件付きUPDATEが0件）。やり直さない（6.2.2）
        raise AppError("ERR-1003", {"field": "qty", "reason": "over_saleable"})
    applog.emit("admin.moved_to_floor")
    return {"data": {"location_code": loc, "sku_code": body.sku_code, "qty": body.qty, **res}}


# ============================================================
# AP-B04  拠点のEC販売可・一時停止（F-809。R-30）
# ============================================================
class LocationPatch(BaseModel):
    ec_saleable: StrictBool | None = None
    suspended: StrictBool | None = None
    # ★R-32。切替以外の項目（F-809）。★拠点コードと区分は変えない（報告に書く）
    name: StrictStr | None = None
    pref_code: StrictStr | None = None
    zip: StrictStr | None = None
    address: StrictStr | None = None
    tel: StrictStr | None = None
    business_days: list[StrictInt] | None = None     # 営業する曜日（0=日〜6=土）
    cutoff_time: StrictStr | None = None             # HH:MM


class LocationCreate(BaseModel):
    location_code: StrictStr
    kind: StrictInt                                  # 1=倉庫 2=店舗
    name: StrictStr
    pref_code: StrictStr
    zip: StrictStr
    address: StrictStr
    tel: StrictStr
    business_days: list[StrictInt]
    cutoff_time: StrictStr
    ec_saleable: StrictBool = False
    suspended: StrictBool = False


class HolidayBody(BaseModel):
    holiday: StrictStr                               # YYYY-MM-DD


def _location_fields(db: Session, body) -> dict:
    """入力を検査して、location の列の値にする。★郵便番号・電話はハイフンを除く（6.3）。"""
    zip_ = cg.digits_only(body.zip) if body.zip is not None else None
    tel = cg.digits_only(body.tel) if body.tel is not None else None
    prefs = {p["pref_code"] for p in repo.prefectures(db)} if body.pref_code is not None else None
    bad = cg.location_input_error(name=body.name, pref_code=body.pref_code, zip_=zip_, address=body.address,
                                  tel=tel, weekdays=body.business_days, cutoff_time=body.cutoff_time,
                                  prefs=prefs)
    if bad:
        raise _field_error(bad)
    out: dict = {}
    if body.name is not None:
        out["name"] = body.name.strip()
    if body.pref_code is not None:
        out["pref_code"] = body.pref_code
    if zip_ is not None:
        out["zip"] = zip_
    if body.address is not None:
        out["address"] = body.address.strip()
    if tel is not None:
        out["tel"] = tel
    if body.business_days is not None:
        out["business_days"] = cg.business_days_mask(body.business_days)
    if body.cutoff_time is not None:
        out["cutoff_time"] = body.cutoff_time + ":00"
    return out


@router.get("/locations/{code}")
def get_location_detail(code: str, db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    role = _guard(operator, "F-809", write=False)
    loc = repo.location_detail(db, code)
    if not loc:
        raise AppError("ERR-1215")
    loc["weekdays"] = [d for d in range(7) if int(loc["business_days"]) >> d & 1]
    return {"data": {**{k: (bool(v) if k in ("suspended", "ec_saleable") else v) for k, v in loc.items()},
                     "prefectures": repo.prefectures(db), "can_edit": authz.can_write(role, "F-809")}}


@router.post("/locations")
def create_location(body: LocationCreate, db: Session = Depends(get_db),
                    operator=Depends(current_operator)) -> dict:
    """F-809 拠点の登録。★倉庫は EC販売可を TRUE 固定（ddl・要件 F-806）。"""
    _guard(operator, "F-809", write=True)
    code = body.location_code.strip().upper()
    if not code:
        raise AppError("ERR-1001", {"field": "location_code"})
    if not cg.LOCATION_CODE_RE.match(code):
        raise AppError("ERR-1002", {"field": "location_code"})
    if body.kind not in (cg.KIND_WAREHOUSE, cg.KIND_STORE):
        raise AppError("ERR-1004", {"field": "kind"})
    f = _location_fields(db, body)
    f.update({"location_code": code, "kind": body.kind, "suspended": body.suspended,
              "ec_saleable": True if body.kind == cg.KIND_WAREHOUSE else body.ec_saleable})
    if not repo.create_location(db, f, by=operator["operator_id"]):
        raise AppError("ERR-1216", {"field": "location_code"})
    applog.emit("admin.location_created")
    return {"data": {"location_code": code}}


@router.post("/locations/{code}/holidays")
def add_location_holiday(code: str, body: HolidayBody, db: Session = Depends(get_db),
                         operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-809", write=True)
    if not repo.get_location(db, code):
        raise AppError("ERR-1215")
    try:
        day = _dt.strptime(body.holiday.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise AppError("ERR-1002", {"field": "holiday"})
    added = repo.add_holiday(db, code, str(day), by=operator["operator_id"])
    return {"data": {"location_code": code, "holiday": str(day), "added": added}}


@router.delete("/locations/{code}/holidays/{day}")
def remove_location_holiday(code: str, day: str, db: Session = Depends(get_db),
                            operator=Depends(current_operator)) -> dict:
    _guard(operator, "F-809", write=True)
    if not repo.get_location(db, code):
        raise AppError("ERR-1215")
    removed = repo.remove_holiday(db, code, day, by=operator["operator_id"])
    return {"data": {"location_code": code, "holiday": day, "removed": removed}}


@router.patch("/locations/{code}")
def patch_location(code: str, body: LocationPatch, db: Session = Depends(get_db),
                   operator=Depends(current_operator)) -> dict:
    """★倉庫は EC販売可を外せない（ddl：倉庫は TRUE 固定。要件 F-806「倉庫に対しては不可を設定できない」）。"""
    _guard(operator, "F-809", write=True)
    loc = repo.get_location(db, code)
    if not loc:
        raise AppError("ERR-1215")
    fields: dict = {}
    if body.ec_saleable is not None:
        if int(loc["kind"]) == 1 and body.ec_saleable is False:
            raise AppError("ERR-1004", {"field": "ec_saleable", "reason": "warehouse"})
        fields["ec_saleable"] = body.ec_saleable
    if body.suspended is not None:
        fields["suspended"] = body.suspended
    other = _location_fields(db, body)
    if not fields and not other:
        raise AppError("ERR-1001", {"field": "body"})
    if fields:
        repo.update_location(db, code, fields, by=operator["operator_id"], before=loc)
    if other:
        repo.edit_location(db, code, other, by=operator["operator_id"])
    applog.emit("admin.location_updated")
    return {"data": {"location_code": code, **{k: bool(v) for k, v in fields.items()},
                     "edited": sorted(other)}}


# ============================================================
# AP-B05  商品×拠点のEC販売の除外（F-806。R-30）
# ============================================================
class ExclusionBody(BaseModel):
    product_code: StrictStr
    location_code: StrictStr


@router.get("/ec-exclusions")
def list_exclusions(db: Session = Depends(get_db), operator=Depends(current_operator),
                    product_code: str | None = None) -> dict:
    _guard(operator, "F-806", write=False)
    return {"data": {"exclusions": repo.exclusions(db, product_code)}}


def _exclusion_target(db: Session, body: ExclusionBody) -> None:
    if not repo.get_product(db, body.product_code):
        raise AppError("ERR-1004", {"field": "product_code"})
    loc = repo.get_location(db, body.location_code)
    if not loc:
        raise AppError("ERR-1004", {"field": "location_code"})
    if int(loc["kind"]) == 1:
        # ★倉庫に対しては不可を設定できない（要件 F-806）。可に戻す（削除）も倉庫には行が無いので同じ扱い
        raise AppError("ERR-1004", {"field": "location_code", "reason": "warehouse"})


@router.put("/ec-exclusions")
def put_exclusion(body: ExclusionBody, db: Session = Depends(get_db),
                  operator=Depends(current_operator)) -> dict:
    """★不可にする＝行を追加（3.2.2 ②）。"""
    _guard(operator, "F-806", write=True)
    _exclusion_target(db, body)
    added = repo.add_exclusion(db, body.product_code, body.location_code, by=operator["operator_id"])
    return {"data": {"excluded": True, "added": added}}


@router.delete("/ec-exclusions")
def delete_exclusion(body: ExclusionBody, db: Session = Depends(get_db),
                     operator=Depends(current_operator)) -> dict:
    """★可に戻す＝行を削除（3.2.2 ②）。"""
    _guard(operator, "F-806", write=True)
    _exclusion_target(db, body)
    removed = repo.remove_exclusion(db, body.product_code, body.location_code, by=operator["operator_id"])
    return {"data": {"excluded": False, "removed": removed}}


# ============================================================
# AP-B09  滞留在庫の抽出（F-807。R-30）
# ============================================================
@router.get("/stocks/stagnant")
def stagnant(db: Session = Depends(get_db), operator=Depends(current_operator)) -> dict:
    """★条件（60日・3点）は要件 F-807 の値。画面から変えさせない（引数を持たない）。"""
    from domain import stock as stock_domain

    role = _guard(operator, "F-807", write=False)
    # ★日数は販売設定（sales_config.stagnant_days。FT-01）から読む。定数で書かない（R-32）
    days = repo.stagnant_days(db)
    rows = repo.stagnant_stocks(db, days=days, min_qty=stock_domain.STAGNANT_MIN_QTY)
    return {"data": {
        "days": days, "min_qty": stock_domain.STAGNANT_MIN_QTY,
        # ★次の操作（EC販売可への切替）ができるかはサーバが返す（受注担当は参照だけ）
        "can_switch_location": authz.can_write(role, "F-809"),
        "can_switch_exclusion": authz.can_write(role, "F-806"),
        "rows": [{**r, "last_sold_at": str(r["last_sold_at"]), "ec_saleable": bool(r["ec_saleable"]),
                  "suspended": bool(r["suspended"]), "excluded": bool(r["excluded"]),
                  # ★いまECで売れるか（BR-05c の3条件）
                  "sellable_on_ec": bool(r["ec_saleable"]) and not bool(r["suspended"]) and not bool(r["excluded"])}
                 for r in rows],
    }}
