# -*- coding: utf-8 -*-
"""ORM のマッピング。テーブル定義の正は db/ddl/ 側（設計 2.2）。

★ここでは db/ddl/*.sql に書いてある列だけを宣言する。
  ORM 側で CREATE TABLE はしない（マイグレーションは db/migrations/ が持つ）。
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CHAR,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "product"

    product_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    category_code: Mapped[str] = mapped_column(String(20))
    item_type_code: Mapped[str] = mapped_column(String(20))
    material: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[int] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped["DateTime"] = mapped_column(DateTime)


class Sku(Base):
    __tablename__ = "sku"

    sku_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    product_code: Mapped[str] = mapped_column(String(20), ForeignKey("product.product_code"))
    color_code: Mapped[str] = mapped_column(String(10))
    size_code: Mapped[str] = mapped_column(String(10))
    common_size_code: Mapped[str] = mapped_column(String(10))


class Stock(Base):
    __tablename__ = "stock"

    sku_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    location_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    section: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)
    reserved_qty: Mapped[int] = mapped_column(Integer)


class Location(Base):
    __tablename__ = "location"

    location_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    kind: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(String(50))
    pref_code: Mapped[str] = mapped_column(CHAR(2))
    suspended: Mapped[bool] = mapped_column(Boolean)
    ec_saleable: Mapped[bool] = mapped_column(Boolean)


class EcExclusion(Base):
    __tablename__ = "ec_exclusion"

    product_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    location_code: Mapped[str] = mapped_column(String(10), primary_key=True)


class ProductImage(Base):
    __tablename__ = "product_image"

    product_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    color_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    sort_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    url: Mapped[str] = mapped_column(String(500))


class Color(Base):
    __tablename__ = "color"

    color_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    sort_no: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean)


class Size(Base):
    __tablename__ = "size"

    size_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    sort_no: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean)


class Category(Base):
    __tablename__ = "category"

    category_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    parent_code: Mapped[str | None] = mapped_column(String(20))
    sort_no: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean)


class Cart(Base):
    """T-19。★主キーは (cart_key, sku_code)。同一SKUの明細は2本作れない。"""

    __tablename__ = "cart"

    cart_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_kind: Mapped[int] = mapped_column(SmallInteger)
    qty: Mapped[int] = mapped_column(Integer)
    added_at: Mapped["DateTime"] = mapped_column(DateTime)


class SalesConfig(Base):
    """T-30。送料・送料無料の線・税率の正。"""

    __tablename__ = "sales_config"

    effective_from: Mapped["Date"] = mapped_column(Date, primary_key=True)
    tax_rate: Mapped[float] = mapped_column(Numeric(4, 3))
    shipping_fee: Mapped[int] = mapped_column(Integer)
    free_shipping_line: Mapped[int] = mapped_column(Integer)


class Order(Base):
    """T-20。★origin_session_id は R-12 で足した（7.2.2a）。"""

    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    member_id: Mapped[str | None] = mapped_column(String(20))
    origin_session_id: Mapped[str | None] = mapped_column(CHAR(64))
    orderer_name: Mapped[str] = mapped_column(String(50))
    orderer_email: Mapped[str] = mapped_column(String(254))
    status: Mapped[int] = mapped_column(SmallInteger)
    receive_method: Mapped[int] = mapped_column(SmallInteger)
    ship_name: Mapped[str] = mapped_column(String(50))
    ship_zip: Mapped[str] = mapped_column(CHAR(7))
    ship_pref_code: Mapped[str] = mapped_column(CHAR(2))
    ship_address: Mapped[str] = mapped_column(String(100))
    ship_tel: Mapped[str] = mapped_column(String(11))
    item_total: Mapped[int] = mapped_column(Integer)
    discount_amount: Mapped[int] = mapped_column(Integer)
    shipping_fee: Mapped[int] = mapped_column(Integer)
    tax_amount: Mapped[int] = mapped_column(Integer)
    total_amount: Mapped[int] = mapped_column(Integer)
    # BR-16。★1注文に1枚のみ。併用しない
    coupon_code: Mapped[str | None] = mapped_column(String(20))
    # 6.2.6。★成立してカートから消したら NULL に戻す（二重に減らさない）
    cart_key: Mapped[str | None] = mapped_column(String(64))


class OrderLine(Base):
    __tablename__ = "order_line"

    order_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    line_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(20))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    tax_rate: Mapped[float] = mapped_column(Numeric(4, 3))
    allocated_discount: Mapped[int] = mapped_column(Integer)
    alloc_location_code: Mapped[str | None] = mapped_column(String(10))
    alloc_status: Mapped[int] = mapped_column(SmallInteger)
    alloc_qty: Mapped[int] = mapped_column(Integer)


class OrderStatusLog(Base):
    __tablename__ = "order_status_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(20))
    status_from: Mapped[int | None] = mapped_column(SmallInteger)
    status_to: Mapped[int] = mapped_column(SmallInteger)
    changed_by: Mapped[int] = mapped_column(SmallInteger)
    operator_id: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(200))


class PaymentTx(Base):
    """T-23。★冪等キーは INSERT の1回で決める（7.2.1）。"""

    __tablename__ = "payment_tx"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(20))
    shipment_id: Mapped[int | None] = mapped_column(Integer)
    return_req_id: Mapped[str | None] = mapped_column(String(20))
    tx_kind: Mapped[int] = mapped_column(SmallInteger)
    provider_tx_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(CHAR(36))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[int] = mapped_column(SmallInteger)
    started_at: Mapped["DateTime | None"] = mapped_column(DateTime)
    attempt_count: Mapped[int] = mapped_column(SmallInteger)
    response_code: Mapped[str | None] = mapped_column(String(20))


class Prefecture(Base):
    __tablename__ = "prefecture"

    pref_code: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(8))
    region: Mapped[int] = mapped_column(SmallInteger)
