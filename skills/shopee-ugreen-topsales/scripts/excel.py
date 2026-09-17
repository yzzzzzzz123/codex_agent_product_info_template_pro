"""Create the UGREEN Top Sales skill's single Excel deliverable.

The module deliberately accepts duck-typed scraper records.  This keeps the
workbook writer independent from the browser implementation while still
validating the fields that make the export useful.  A workbook is first saved
beside the requested destination, reopened and verified, and only then moved
into place atomically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.cell import Cell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


__all__ = ["WorkbookStats", "validate_excel", "write_excel"]


SHEET_NAMES = ("商品汇总", "SKU明细", "图片明细", "抓取核验")
HEADER_ROW = 6
DATA_ROW = HEADER_ROW + 1

SUMMARY_HEADERS = (
    "全店排名",
    "列表页",
    "页内排名",
    "店铺ID",
    "商品ID",
    "商品标题",
    "当前价格 (PHP)",
    "月销原文",
    "月销下界",
    "月销状态",
    "SKU数",
    "主图链接",
    "副图数",
    "商品链接",
)
SKU_HEADERS = (
    "全店排名",
    "列表页",
    "店铺ID",
    "商品ID",
    "商品标题",
    "SKU Model ID",
    "SKU规格",
    "SKU图片链接",
    "商品链接",
)
IMAGE_HEADERS = (
    "全店排名",
    "列表页",
    "店铺ID",
    "商品ID",
    "商品标题",
    "图片类型",
    "图片序号",
    "图片链接",
    "商品链接",
)
AUDIT_HEADERS = ("核验项", "结果", "说明")

STORE_URL = "https://shopee.ph/ugreen.ph?page=0&sortBy=sales&tab=0"
TEXT_FORMAT = "@"
CURRENCY_FORMAT = '"₱"#,##0.00'
INTEGER_FORMAT = "#,##0"
DATETIME_FORMAT = "yyyy-mm-dd hh:mm:ss"

_DARK_GREEN = "1F5C45"
_MEDIUM_GREEN = "4F8A63"
_LIGHT_GREEN = "EAF3ED"
_ACCENT_GREEN = "78A942"
_WHITE = "FFFFFF"
_TEXT = "24332B"
_LIGHT_BORDER = "CDD9D1"
_LINK = "0563C1"
_PASS = "2E7D32"
_FAIL = "B3261E"
_PASS_FILL = "E6F4EA"
_FAIL_FILL = "FCE8E6"

_PDP_IDENTITY_PATTERNS = (
    re.compile(r"(?:-i\.|/i\.)(\d+)\.(\d+)(?:/)?$", re.I),
    re.compile(r"/product/(\d+)/(\d+)(?:/)?$", re.I),
)

_THIN_BORDER = Border(
    bottom=Side(style="thin", color=_LIGHT_BORDER),
)


@dataclass(frozen=True, slots=True)
class WorkbookStats:
    """Counts proven by reopening the saved workbook."""

    product_count: int
    sku_count: int
    main_image_count: int
    secondary_image_count: int
    audit_status: str


@dataclass(frozen=True, slots=True)
class _SkuView:
    model_id: str
    props: str
    image_url: str | None


@dataclass(frozen=True, slots=True)
class _ProductView:
    global_rank: int
    list_page: int
    source_position: int
    shop_id: str
    item_id: str
    title: str
    product_url: str
    price_php: int | float | None
    monthly_sales_text: str | None
    monthly_sales_lower_bound: int | None
    monthly_sales_status: str
    skus: tuple[_SkuView, ...]
    main_image_url: str | None
    secondary_image_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ExportView:
    store_url: str
    captured_at: datetime | str
    products: tuple[_ProductView, ...]
    audit: Any


@dataclass(frozen=True, slots=True)
class _Expected:
    product_count: int
    sku_count: int
    main_image_count: int
    secondary_image_count: int
    summary_hyperlink_count: int
    sku_hyperlink_count: int
    image_hyperlink_count: int
    audit_row_count: int
    audit_status: str


def _has(obj: Any, name: str) -> bool:
    if isinstance(obj, Mapping):
        return name in obj
    return hasattr(obj, name)


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    saw_none = False
    for name in names:
        if isinstance(obj, Mapping):
            if name not in obj:
                continue
            value = obj[name]
        elif hasattr(obj, name):
            value = getattr(obj, name)
        else:
            continue
        if value is not None:
            return value
        saw_none = True
    return None if saw_none else default


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, Sequence):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def _clean_text(value: Any, *, limit: int = 32_767) -> str:
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    return text[:limit]


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _clean_text(value)


def _integer(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Expected an integer, got {value!r}") from exc


def _number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not a valid numeric value: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite numeric value: {value!r}")
        return int(value) if value.is_integer() else value
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Expected a numeric value, got {value!r}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"Non-finite numeric value: {value!r}")
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return _integer(value, default=0)


def _format_props(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            if item is None or item == "":
                continue
            if isinstance(item, (list, tuple)):
                item_text = " / ".join(_clean_text(part) for part in item)
            else:
                item_text = _clean_text(item)
            parts.append(f"{_clean_text(key)}: {item_text}")
        return ", ".join(parts)
    if isinstance(value, (list, tuple)):
        return ", ".join(_clean_text(item) for item in value)
    return _clean_text(value)


def _monthly_status(observation: Any, sales_text: str | None) -> str:
    if observation is None:
        return "已展示" if sales_text else "未展示"
    normalized = str(observation).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"displayed", "shown", "observed", "已展示"}:
        return "已展示"
    if normalized in {"not_displayed", "not_shown", "missing", "unobserved", "未展示"}:
        return "未展示"
    if "not" in normalized or "未" in normalized or "missing" in normalized:
        return "未展示"
    return "已展示" if sales_text else "未展示"


def _local_excel_datetime(value: Any) -> datetime | str:
    if value is None:
        return datetime.now().replace(microsecond=0)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value.replace(microsecond=0)
    return _clean_text(value)


def _normalise_export(result: Any) -> _ExportView:
    raw_products = _as_sequence(_get(result, "products", default=[]))
    if not raw_products:
        raise ValueError("Cannot create an Excel workbook without products")

    products: list[_ProductView] = []
    for index, raw in enumerate(raw_products, start=1):
        global_rank = _integer(_get(raw, "global_rank", "rank"), default=index)
        if _has(raw, "source_page"):
            list_page = _integer(_get(raw, "source_page"), default=0) + 1
        else:
            list_page = _integer(_get(raw, "list_page", "page"), default=1)
        source_position = _integer(
            _get(raw, "source_position", "page_rank", "position"),
            default=((global_rank - 1) % 30) + 1,
        )
        shop_id = _id_text(_get(raw, "shop_id"))
        item_id = _id_text(_get(raw, "item_id"))
        title = _clean_text(_get(raw, "title", "name", default=""))
        product_url = _clean_text(_get(raw, "product_url", "url", default=""))
        if not shop_id or not item_id:
            raise ValueError(f"Product rank {global_rank} is missing shop_id or item_id")
        if not title:
            raise ValueError(f"Product {shop_id}.{item_id} is missing a title")
        if not _is_http_url(product_url):
            raise ValueError(f"Product {shop_id}.{item_id} has an invalid URL: {product_url!r}")

        sales_text_value = _get(raw, "monthly_sales_text", "monthly_sales_raw")
        sales_text = _clean_text(sales_text_value) if sales_text_value not in (None, "") else None
        lower_bound = _optional_int(
            _get(raw, "monthly_sales_count_lower_bound", "monthly_sales_lower_bound")
        )
        status = _monthly_status(_get(raw, "monthly_sales_observation", "monthly_sales_status"), sales_text)

        skus: list[_SkuView] = []
        for sku in _as_sequence(_get(raw, "skus", default=[])):
            skus.append(
                _SkuView(
                    model_id=_id_text(_get(sku, "model_id", "sku_model_id", "id")),
                    props=_format_props(_get(sku, "sku_props", "props", "specification")),
                    image_url=_optional_text(_get(sku, "sku_image_url", "image_url")),
                )
            )

        main_image_url = _optional_text(_get(raw, "main_image_url", "main_image"))
        secondary_images = tuple(
            text
            for value in _as_sequence(
                _get(raw, "secondary_image_urls", "secondary_images", default=[])
            )
            if (text := _optional_text(value)) is not None
        )
        products.append(
            _ProductView(
                global_rank=global_rank,
                list_page=list_page,
                source_position=source_position,
                shop_id=shop_id,
                item_id=item_id,
                title=title,
                product_url=product_url,
                price_php=_number(_get(raw, "price_php", "current_price", "price")),
                monthly_sales_text=sales_text,
                monthly_sales_lower_bound=lower_bound,
                monthly_sales_status=status,
                skus=tuple(skus),
                main_image_url=main_image_url,
                secondary_image_urls=secondary_images,
            )
        )

    ranks = [product.global_rank for product in products]
    if ranks != list(range(1, len(products) + 1)):
        raise ValueError("Product global_rank values must be contiguous and ordered from 1")
    identities = [(product.shop_id, product.item_id) for product in products]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate shop_id + item_id identities remain in the product list")

    store_url = _clean_text(_get(result, "store_url", default=STORE_URL))
    if not _is_http_url(store_url):
        raise ValueError(f"Invalid store URL: {store_url!r}")
    return _ExportView(
        store_url=store_url,
        captured_at=_local_excel_datetime(_get(result, "captured_at", "scraped_at")),
        products=tuple(products),
        audit=_get(result, "audit"),
    )


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return _clean_text(value)


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _audit_int(audit: Any, name: str, fallback: int) -> int:
    return _integer(_get(audit, name), default=fallback)


def _audit_rows(view: _ExportView) -> tuple[list[tuple[Any, Any, str]], str]:
    products = view.products
    product_count = len(products)
    sku_count = sum(len(product.skus) for product in products)
    main_count = sum(bool(product.main_image_url) for product in products)
    secondary_count = sum(len(product.secondary_image_urls) for product in products)
    products_with_skus = sum(bool(product.skus) for product in products)
    missing_monthly = sum(product.monthly_sales_status == "未展示" for product in products)

    page_count = _audit_int(view.audit, "list_page_count", max(product.list_page for product in products))
    occurrences = _audit_int(view.audit, "list_input_product_occurrences", product_count)
    duplicate_count = _audit_int(
        view.audit,
        "list_duplicate_occurrence_count",
        max(0, occurrences - product_count),
    )
    detail_success = _audit_int(view.audit, "detail_success_count", product_count)
    detail_failure = _audit_int(view.audit, "detail_failure_count", 0)
    listed_product_count = _audit_int(view.audit, "listed_product_count", product_count)
    audit_missing_monthly = _audit_int(
        view.audit,
        "products_without_monthly_sales_display",
        missing_monthly,
    )

    invalid_product_urls = sum(not _is_http_url(product.product_url) for product in products)
    invalid_image_urls = 0
    for product in products:
        invalid_image_urls += not _is_http_url(product.main_image_url)
        invalid_image_urls += sum(not _is_http_url(url) for url in product.secondary_image_urls)
        invalid_image_urls += sum(
            bool(sku.image_url) and not _is_http_url(sku.image_url) for sku in product.skus
        )
    ranks_contiguous = [product.global_rank for product in products] == list(range(1, product_count + 1))

    passed = (
        product_count > 0
        and page_count > 0
        and listed_product_count == product_count
        and occurrences - duplicate_count == product_count
        and ranks_contiguous
        and detail_success == product_count
        and detail_failure == 0
        and audit_missing_monthly == missing_monthly
        and products_with_skus == product_count
        and main_count == product_count
        and invalid_product_urls == 0
        and invalid_image_urls == 0
    )
    status = "通过" if passed else "未通过"
    rows: list[tuple[Any, Any, str]] = [
        ("店铺 URL", view.store_url, "固定抓取 UGREEN 菲律宾店铺"),
        ("排序方式", "Top Sales", "列表 URL 使用 sortBy=sales"),
        ("列表总页数", page_count, "动态遍历列表分页"),
        ("商品卡出现次数", occurrences, "包含跨页重复展示"),
        ("跨页重复次数", duplicate_count, "按 shop_id + item_id 去重"),
        ("唯一商品数", product_count, "商品汇总行数"),
        ("全店排名连续", "是" if ranks_contiguous else "否", "应从 1 连续排列"),
        ("成功进入详情页", detail_success, "浏览器真实导航并匹配 PDP 身份"),
        ("详情页失败数", detail_failure, "重试后仍失败的商品"),
        ("未展示月销商品数", audit_missing_monthly, "留空并标记未展示，不按 0 处理"),
        ("SKU 总数", sku_count, "SKU 明细行数"),
        ("有 SKU 的商品数", products_with_skus, ""),
        ("主图数", main_count, "每个商品最多一张主图"),
        ("副图数", secondary_count, "保持详情页图库顺序"),
        ("无效商品 URL 数", invalid_product_urls, "应为 0"),
        ("无效图片 URL 数", invalid_image_urls, "应为 0；缺失主图也计入"),
        ("完整性结论", status, "全部唯一商品均成功写入 Excel" if passed else "存在未通过的完整性检查"),
    ]
    return rows, status


def _set_text(cell: Cell, value: Any, *, identifier: bool = False) -> None:
    if value is None or value == "":
        cell.value = None
    else:
        cell.value = _clean_text(value)
        # openpyxl interprets leading '=' as a formula unless its type is reset.
        cell.data_type = "s"
    if identifier:
        cell.number_format = TEXT_FORMAT


def _set_number(cell: Cell, value: int | float | None, number_format: str) -> None:
    cell.value = value
    cell.number_format = number_format


def _set_link(cell: Cell, value: str | None) -> None:
    _set_text(cell, value)
    if value and _is_http_url(value):
        cell.hyperlink = value
        cell.font = Font(name="Aptos", size=10, color=_LINK, underline="single")


def _style_title(ws: Any, title: str, last_column: int) -> None:
    for column in range(1, last_column + 1):
        cell = ws.cell(row=2, column=column)
        cell.fill = PatternFill("solid", fgColor=_DARK_GREEN)
        cell.border = Border()
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    cell = ws.cell(row=2, column=1)
    _set_text(cell, title)
    cell.font = Font(name="Aptos Display", size=16, bold=True, color=_WHITE)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 30


def _style_metadata_pair(ws: Any, row: int, label_column: int, label: str, value: Any) -> None:
    label_cell = ws.cell(row=row, column=label_column)
    value_cell = ws.cell(row=row, column=label_column + 1)
    _set_text(label_cell, label)
    label_cell.font = Font(name="Aptos", size=10, bold=True, color=_DARK_GREEN)
    label_cell.fill = PatternFill("solid", fgColor=_LIGHT_GREEN)
    label_cell.alignment = Alignment(vertical="center")
    if isinstance(value, datetime):
        value_cell.value = value
        value_cell.number_format = DATETIME_FORMAT
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        value_cell.value = value
        value_cell.number_format = INTEGER_FORMAT
    else:
        _set_text(value_cell, value)
    value_cell.font = Font(name="Aptos", size=10, color=_TEXT)
    value_cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[row].height = 22


def _style_headers(ws: Any, headers: Sequence[str]) -> None:
    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row=HEADER_ROW, column=column)
        _set_text(cell, header)
        cell.font = Font(name="Aptos", size=10, bold=True, color=_WHITE)
        cell.fill = PatternFill("solid", fgColor=_MEDIUM_GREEN)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(
            left=Side(style="thin", color=_WHITE),
            right=Side(style="thin", color=_WHITE),
        )
    ws.row_dimensions[HEADER_ROW].height = 31


def _configure_sheet(ws: Any, *, tab_color: str, default_height: float = 26) -> None:
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    ws.freeze_panes = f"A{DATA_ROW}"
    ws.sheet_properties.tabColor = tab_color
    ws.sheet_format.defaultRowHeight = default_height
    ws.auto_filter.ref = None
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.25
    ws.page_margins.right = 0.25
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5
    ws.print_title_rows = f"1:{HEADER_ROW}"


def _set_widths(ws: Any, widths: Sequence[float]) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _add_table(ws: Any, *, name: str, last_row: int, last_column: int) -> None:
    reference = f"A{HEADER_ROW}:{get_column_letter(last_column)}{max(last_row, HEADER_ROW)}"
    ws.auto_filter.ref = reference
    if last_row <= HEADER_ROW:
        return
    table = Table(displayName=name, ref=reference)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium4",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)


def _style_data_cell(
    cell: Cell,
    *,
    horizontal: str = "left",
    wrap: bool = False,
) -> None:
    if cell.hyperlink is None:
        cell.font = Font(name="Aptos", size=10, color=_TEXT)
    cell.alignment = Alignment(
        horizontal=horizontal,
        vertical="top",
        wrap_text=wrap,
    )
    cell.border = _THIN_BORDER


def _build_summary_sheet(wb: Workbook, view: _ExportView) -> None:
    ws = wb.active
    ws.title = SHEET_NAMES[0]
    _configure_sheet(ws, tab_color=_DARK_GREEN, default_height=34)
    ws.page_setup.orientation = "landscape"
    _style_title(ws, "UGREEN Shopee Top Sales 全店商品", len(SUMMARY_HEADERS))

    product_count = len(view.products)
    sku_count = sum(len(product.skus) for product in view.products)
    main_count = sum(bool(product.main_image_url) for product in view.products)
    secondary_count = sum(len(product.secondary_image_urls) for product in view.products)
    _style_metadata_pair(ws, 3, 1, "采集时间", view.captured_at)
    _style_metadata_pair(ws, 3, 4, "商品数", product_count)
    _style_metadata_pair(ws, 3, 6, "SKU数", sku_count)
    _style_metadata_pair(ws, 3, 8, "主图数", main_count)
    _style_metadata_pair(ws, 3, 10, "副图数", secondary_count)
    _style_metadata_pair(ws, 3, 12, "排序", "Top Sales")
    _style_metadata_pair(ws, 4, 1, "店铺来源", view.store_url)
    _set_link(ws.cell(row=4, column=2), view.store_url)
    ws.cell(row=4, column=2).alignment = Alignment(vertical="center")
    _style_headers(ws, SUMMARY_HEADERS)

    for row_number, product in enumerate(view.products, start=DATA_ROW):
        values = (
            product.global_rank,
            product.list_page,
            product.source_position,
            product.shop_id,
            product.item_id,
            product.title,
            product.price_php,
            product.monthly_sales_text,
            product.monthly_sales_lower_bound,
            product.monthly_sales_status,
            len(product.skus),
            product.main_image_url,
            len(product.secondary_image_urls),
            product.product_url,
        )
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row=row_number, column=column)
            if column in {4, 5}:
                _set_text(cell, value, identifier=True)
            elif column in {12, 14}:
                _set_link(cell, value)
            elif column == 7:
                _set_number(cell, value, CURRENCY_FORMAT)
            elif column in {1, 2, 3, 9, 11, 13}:
                _set_number(cell, value, INTEGER_FORMAT)
            else:
                _set_text(cell, value)
            _style_data_cell(
                cell,
                horizontal="center" if column in {1, 2, 3, 4, 5, 9, 10, 11, 13} else "left",
                wrap=column in {6, 8, 12, 14},
            )

    _set_widths(ws, (10, 9, 10, 15, 16, 54, 18, 20, 13, 12, 10, 48, 10, 52))
    _add_table(
        ws,
        name="ProductSummary",
        last_row=HEADER_ROW + product_count,
        last_column=len(SUMMARY_HEADERS),
    )


def _build_sku_sheet(wb: Workbook, view: _ExportView) -> None:
    ws = wb.create_sheet(SHEET_NAMES[1])
    _configure_sheet(ws, tab_color=_MEDIUM_GREEN, default_height=30)
    ws.page_setup.orientation = "landscape"
    _style_title(ws, "UGREEN Shopee SKU 明细", len(SKU_HEADERS))
    sku_count = sum(len(product.skus) for product in view.products)
    _style_metadata_pair(ws, 3, 1, "记录数", sku_count)
    _style_metadata_pair(ws, 3, 4, "商品数", len(view.products))
    _style_metadata_pair(ws, 4, 1, "说明", "本表列出详情页公开 SKU；商品当前价格见“商品汇总”。")
    _style_headers(ws, SKU_HEADERS)

    row_number = DATA_ROW
    for product in view.products:
        for sku in product.skus:
            values = (
                product.global_rank,
                product.list_page,
                product.shop_id,
                product.item_id,
                product.title,
                sku.model_id,
                sku.props,
                sku.image_url,
                product.product_url,
            )
            for column, value in enumerate(values, start=1):
                cell = ws.cell(row=row_number, column=column)
                if column in {3, 4, 6}:
                    _set_text(cell, value, identifier=True)
                elif column in {8, 9}:
                    _set_link(cell, value)
                elif column in {1, 2}:
                    _set_number(cell, value, INTEGER_FORMAT)
                else:
                    _set_text(cell, value)
                _style_data_cell(
                    cell,
                    horizontal="center" if column in {1, 2, 3, 4, 6} else "left",
                    wrap=column in {5, 7, 8, 9},
                )
            row_number += 1

    _set_widths(ws, (10, 9, 15, 16, 50, 20, 38, 48, 52))
    _add_table(
        ws,
        name="SkuDetail",
        last_row=row_number - 1,
        last_column=len(SKU_HEADERS),
    )


def _build_image_sheet(wb: Workbook, view: _ExportView) -> None:
    ws = wb.create_sheet(SHEET_NAMES[2])
    _configure_sheet(ws, tab_color=_ACCENT_GREEN, default_height=28)
    ws.page_setup.orientation = "landscape"
    _style_title(ws, "UGREEN Shopee 商品图片明细", len(IMAGE_HEADERS))
    main_count = sum(bool(product.main_image_url) for product in view.products)
    secondary_count = sum(len(product.secondary_image_urls) for product in view.products)
    _style_metadata_pair(ws, 3, 1, "图片记录数", main_count + secondary_count)
    _style_metadata_pair(ws, 3, 4, "主图数", main_count)
    _style_metadata_pair(ws, 3, 6, "副图数", secondary_count)
    _style_metadata_pair(ws, 4, 1, "说明", "每个商品的主图列在前，副图保持详情页图库顺序。")
    _style_headers(ws, IMAGE_HEADERS)

    row_number = DATA_ROW
    for product in view.products:
        image_rows: list[tuple[str, int, str]] = []
        if product.main_image_url:
            image_rows.append(("主图", 1, product.main_image_url))
        image_rows.extend(
            ("副图", image_index, image_url)
            for image_index, image_url in enumerate(product.secondary_image_urls, start=1)
        )
        for image_type, image_index, image_url in image_rows:
            values = (
                product.global_rank,
                product.list_page,
                product.shop_id,
                product.item_id,
                product.title,
                image_type,
                image_index,
                image_url,
                product.product_url,
            )
            for column, value in enumerate(values, start=1):
                cell = ws.cell(row=row_number, column=column)
                if column in {3, 4}:
                    _set_text(cell, value, identifier=True)
                elif column in {8, 9}:
                    _set_link(cell, value)
                elif column in {1, 2, 7}:
                    _set_number(cell, value, INTEGER_FORMAT)
                else:
                    _set_text(cell, value)
                _style_data_cell(
                    cell,
                    horizontal="center" if column in {1, 2, 3, 4, 6, 7} else "left",
                    wrap=column in {5, 8, 9},
                )
            row_number += 1

    _set_widths(ws, (10, 9, 15, 16, 50, 11, 10, 54, 52))
    _add_table(
        ws,
        name="ImageDetail",
        last_row=row_number - 1,
        last_column=len(IMAGE_HEADERS),
    )


def _build_audit_sheet(
    wb: Workbook,
    view: _ExportView,
    rows: Sequence[tuple[Any, Any, str]],
    status: str,
) -> None:
    ws = wb.create_sheet(SHEET_NAMES[3])
    _configure_sheet(ws, tab_color=_PASS if status == "通过" else _FAIL, default_height=25)
    ws.page_setup.orientation = "portrait"
    _style_title(ws, "UGREEN Shopee 全店抓取核验", len(AUDIT_HEADERS))
    _style_metadata_pair(ws, 3, 1, "核验状态", status)
    status_cell = ws.cell(row=3, column=2)
    status_cell.font = Font(
        name="Aptos",
        size=10,
        bold=True,
        color=_PASS if status == "通过" else _FAIL,
    )
    status_cell.fill = PatternFill(
        "solid",
        fgColor=_PASS_FILL if status == "通过" else _FAIL_FILL,
    )
    _style_metadata_pair(ws, 4, 1, "范围", "UGREEN Top Sales 全部分页与全部详情页")
    _style_headers(ws, AUDIT_HEADERS)

    for row_number, values in enumerate(rows, start=DATA_ROW):
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row=row_number, column=column)
            if column == 2 and values[0] == "店铺 URL":
                _set_link(cell, value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                _set_number(cell, value, INTEGER_FORMAT)
            else:
                _set_text(cell, value)
            _style_data_cell(cell, wrap=True)
        if values[0] == "完整性结论":
            result_cell = ws.cell(row=row_number, column=2)
            result_cell.font = Font(
                name="Aptos",
                size=10,
                bold=True,
                color=_PASS if status == "通过" else _FAIL,
            )
            result_cell.fill = PatternFill(
                "solid",
                fgColor=_PASS_FILL if status == "通过" else _FAIL_FILL,
            )

    _set_widths(ws, (28, 38, 58))
    _add_table(
        ws,
        name="CrawlAudit",
        last_row=HEADER_ROW + len(rows),
        last_column=len(AUDIT_HEADERS),
    )


def _build_workbook(view: _ExportView) -> tuple[Workbook, _Expected]:
    audit_rows, audit_status = _audit_rows(view)
    wb = Workbook()
    wb.properties.creator = "shopees_ugreen_topsales_scraper"
    wb.properties.title = "UGREEN Shopee Top Sales"
    wb.properties.subject = "UGREEN Shopee Philippines Top Sales product export"
    wb.properties.description = "Product, SKU and image records collected from product detail pages."
    wb.properties.keywords = "Shopee, UGREEN, Top Sales"
    wb.properties.created = view.captured_at if isinstance(view.captured_at, datetime) else datetime.now()
    wb.properties.modified = wb.properties.created

    _build_summary_sheet(wb, view)
    _build_sku_sheet(wb, view)
    _build_image_sheet(wb, view)
    _build_audit_sheet(wb, view, audit_rows, audit_status)
    wb.active = 0

    summary_hyperlinks = sum(bool(product.main_image_url) + 1 for product in view.products) + 1
    sku_hyperlinks = sum(
        1 + bool(sku.image_url)
        for product in view.products
        for sku in product.skus
    )
    image_hyperlinks = 2 * sum(
        bool(product.main_image_url) + len(product.secondary_image_urls)
        for product in view.products
    )
    expected = _Expected(
        product_count=len(view.products),
        sku_count=sum(len(product.skus) for product in view.products),
        main_image_count=sum(bool(product.main_image_url) for product in view.products),
        secondary_image_count=sum(len(product.secondary_image_urls) for product in view.products),
        summary_hyperlink_count=summary_hyperlinks,
        sku_hyperlink_count=sku_hyperlinks,
        image_hyperlink_count=image_hyperlinks,
        audit_row_count=len(audit_rows),
        audit_status=audit_status,
    )
    return wb, expected


def _assert_headers(ws: Any, expected: Sequence[str]) -> None:
    if ws.max_column != len(expected):
        raise ValueError(
            f"Unexpected column count in sheet {ws.title!r}: "
            f"expected {len(expected)}, got {ws.max_column}"
        )
    actual = tuple(ws.cell(row=HEADER_ROW, column=column).value for column in range(1, len(expected) + 1))
    if actual != tuple(expected):
        raise ValueError(f"Unexpected headers in sheet {ws.title!r}: {actual!r}")


def _assert_ids_are_text(ws: Any, rows: range, columns: Sequence[int]) -> None:
    for row in rows:
        for column in columns:
            cell = ws.cell(row=row, column=column)
            if cell.value in (None, ""):
                continue
            if cell.data_type != "s" or not isinstance(cell.value, str):
                raise ValueError(f"Identifier {ws.title}!{cell.coordinate} was not stored as text")
            if cell.number_format != TEXT_FORMAT:
                raise ValueError(f"Identifier {ws.title}!{cell.coordinate} lacks text formatting")


def _assert_links(ws: Any, columns: Sequence[int], expected_count: int) -> None:
    count = 0
    for row in range(DATA_ROW, ws.max_row + 1):
        for column in columns:
            cell = ws.cell(row=row, column=column)
            if cell.value in (None, ""):
                continue
            if cell.hyperlink is None or cell.hyperlink.target != cell.value:
                raise ValueError(f"Missing hyperlink in {ws.title}!{cell.coordinate}")
            count += 1
    if count != expected_count:
        raise ValueError(
            f"Hyperlink count mismatch in {ws.title!r}: expected {expected_count}, got {count}"
        )


def _verify_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"The generated file is not a valid XLSX ZIP container: {path}")
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"Corrupt XLSX ZIP member: {bad_member}")
        members = set(archive.namelist())
        required = {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"}
        missing = required - members
        if missing:
            raise ValueError(f"XLSX container is missing required members: {sorted(missing)}")


def _validate_with_expected(path: Path, expected: _Expected) -> WorkbookStats:
    _verify_zip(path)
    wb = load_workbook(path, data_only=False, read_only=False, keep_links=True)
    try:
        if tuple(wb.sheetnames) != SHEET_NAMES:
            raise ValueError(f"Unexpected worksheet order: {wb.sheetnames!r}")

        summary = wb[SHEET_NAMES[0]]
        sku = wb[SHEET_NAMES[1]]
        images = wb[SHEET_NAMES[2]]
        audit = wb[SHEET_NAMES[3]]
        _assert_headers(summary, SUMMARY_HEADERS)
        _assert_headers(sku, SKU_HEADERS)
        _assert_headers(images, IMAGE_HEADERS)
        _assert_headers(audit, AUDIT_HEADERS)

        expected_rows = {
            SHEET_NAMES[0]: HEADER_ROW + expected.product_count,
            SHEET_NAMES[1]: HEADER_ROW + expected.sku_count,
            SHEET_NAMES[2]: HEADER_ROW + expected.main_image_count + expected.secondary_image_count,
            SHEET_NAMES[3]: HEADER_ROW + expected.audit_row_count,
        }
        for ws in wb.worksheets:
            if ws.max_row != expected_rows[ws.title]:
                raise ValueError(
                    f"Row count mismatch in {ws.title!r}: expected {expected_rows[ws.title]}, got {ws.max_row}"
                )
            if str(ws.freeze_panes) != f"A{DATA_ROW}":
                raise ValueError(f"Freeze pane missing in sheet {ws.title!r}")
            if not ws.auto_filter.ref and not ws.tables:
                raise ValueError(f"Filter missing in sheet {ws.title!r}")
            for row in ws.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        raise ValueError(f"Formula found in {ws.title}!{cell.coordinate}")

        _assert_ids_are_text(
            summary,
            range(DATA_ROW, HEADER_ROW + expected.product_count + 1),
            (4, 5),
        )
        _assert_ids_are_text(
            sku,
            range(DATA_ROW, HEADER_ROW + expected.sku_count + 1),
            (3, 4, 6),
        )
        _assert_ids_are_text(
            images,
            range(DATA_ROW, HEADER_ROW + expected.main_image_count + expected.secondary_image_count + 1),
            (3, 4),
        )

        # The store link is metadata; all other requested links live in data tables.
        store_cell = summary.cell(row=4, column=2)
        if store_cell.hyperlink is None or store_cell.hyperlink.target != store_cell.value:
            raise ValueError("Store source hyperlink is missing from 商品汇总")
        _assert_links(summary, (12, 14), expected.summary_hyperlink_count - 1)
        _assert_links(sku, (8, 9), expected.sku_hyperlink_count)
        _assert_links(images, (8, 9), expected.image_hyperlink_count)

        audit_status = str(audit.cell(row=3, column=2).value or "")
        if audit_status != expected.audit_status:
            raise ValueError(
                f"Audit status mismatch: expected {expected.audit_status!r}, got {audit_status!r}"
            )
        return WorkbookStats(
            product_count=expected.product_count,
            sku_count=expected.sku_count,
            main_image_count=expected.main_image_count,
            secondary_image_count=expected.secondary_image_count,
            audit_status=audit_status,
        )
    finally:
        wb.close()


def _required_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label} must be an integer, got {value!r}")
    if not math.isfinite(float(value)) or int(value) != value:
        raise ValueError(f"{label} must be a finite integer, got {value!r}")
    result = int(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"{label} is outside the allowed range: {result}")
    return result


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _required_http_url(value: Any, label: str) -> str:
    text = _required_text(value, label)
    if not _is_http_url(text):
        raise ValueError(f"{label} is not an HTTP(S) URL: {text!r}")
    return text


def _pdp_identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or not (
            hostname == "shopee.ph" or hostname.endswith(".shopee.ph")
        ):
            return None
        path = unquote(parsed.path)
    except (TypeError, ValueError):
        return None
    for pattern in _PDP_IDENTITY_PATTERNS:
        if match := pattern.search(path):
            return str(int(match.group(1))), str(int(match.group(2)))
    return None


def _validate_store_url(value: Any) -> None:
    text = _required_text(value, "抓取核验/店铺 URL")
    try:
        parsed = urlsplit(text)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid store URL in audit sheet: {text!r}") from exc
    if not (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "shopee.ph"
        and parsed.path.rstrip("/") == "/ugreen.ph"
        and query.get("page") == ["0"]
        and query.get("sortBy") == ["sales"]
        and query.get("tab") == ["0"]
    ):
        raise ValueError(f"Audit sheet contains an unexpected store URL: {text!r}")


def validate_excel(path: str | os.PathLike[str]) -> WorkbookStats:
    """Reopen and independently validate the canonical workbook and its joins."""

    workbook_path = Path(path)
    _verify_zip(workbook_path)
    wb = load_workbook(workbook_path, data_only=False, read_only=False, keep_links=True)
    try:
        if tuple(wb.sheetnames) != SHEET_NAMES:
            raise ValueError(f"Unexpected worksheet order: {wb.sheetnames!r}")
        summary = wb[SHEET_NAMES[0]]
        sku = wb[SHEET_NAMES[1]]
        images = wb[SHEET_NAMES[2]]
        audit = wb[SHEET_NAMES[3]]
        _assert_headers(summary, SUMMARY_HEADERS)
        _assert_headers(sku, SKU_HEADERS)
        _assert_headers(images, IMAGE_HEADERS)
        _assert_headers(audit, AUDIT_HEADERS)
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        raise ValueError(f"Formula found in {ws.title}!{cell.coordinate}")

        product_count = summary.max_row - HEADER_ROW
        sku_count = sku.max_row - HEADER_ROW
        if product_count < 1 or sku_count < 1:
            raise ValueError("Workbook contains no product or SKU records")
        _assert_ids_are_text(
            summary,
            range(DATA_ROW, summary.max_row + 1),
            (4, 5),
        )
        _assert_ids_are_text(
            sku,
            range(DATA_ROW, sku.max_row + 1),
            (3, 4, 6),
        )
        _assert_ids_are_text(
            images,
            range(DATA_ROW, images.max_row + 1),
            (3, 4),
        )

        products: dict[tuple[str, str], dict[str, Any]] = {}
        pages: set[int] = set()
        missing_monthly = 0
        for row in range(DATA_ROW, summary.max_row + 1):
            rank = _required_int(summary.cell(row, 1).value, f"商品汇总!A{row}", minimum=1)
            if rank != row - HEADER_ROW:
                raise ValueError(f"Non-contiguous product rank in 商品汇总!A{row}")
            page = _required_int(summary.cell(row, 2).value, f"商品汇总!B{row}", minimum=1)
            _required_int(
                summary.cell(row, 3).value,
                f"商品汇总!C{row}",
                minimum=1,
                maximum=30,
            )
            pages.add(page)
            shop_id = _required_text(summary.cell(row, 4).value, f"商品汇总!D{row}")
            item_id = _required_text(summary.cell(row, 5).value, f"商品汇总!E{row}")
            if shop_id != "64922227" or not item_id.isdigit():
                raise ValueError(f"Invalid product identity in 商品汇总 row {row}")
            key = (shop_id, item_id)
            if key in products:
                raise ValueError(f"Duplicate product identity in 商品汇总 row {row}: {key!r}")
            title = _required_text(summary.cell(row, 6).value, f"商品汇总!F{row}")
            price = summary.cell(row, 7).value
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float, Decimal))
                or not math.isfinite(float(price))
                or price < 0
            ):
                raise ValueError(f"Invalid product price in 商品汇总!G{row}: {price!r}")
            monthly_status = summary.cell(row, 10).value
            if monthly_status not in {"已展示", "未展示"}:
                raise ValueError(f"Invalid monthly-sales status in 商品汇总!J{row}")
            if monthly_status == "未展示":
                missing_monthly += 1
                if summary.cell(row, 8).value not in (None, "") or summary.cell(row, 9).value not in (None, ""):
                    raise ValueError(f"Hidden monthly sales must stay blank in 商品汇总 row {row}")
            else:
                _required_text(summary.cell(row, 8).value, f"商品汇总!H{row}")
                _required_int(summary.cell(row, 9).value, f"商品汇总!I{row}")
            expected_skus = _required_int(
                summary.cell(row, 11).value,
                f"商品汇总!K{row}",
                minimum=1,
            )
            main_url = _required_http_url(summary.cell(row, 12).value, f"商品汇总!L{row}")
            expected_secondary = _required_int(
                summary.cell(row, 13).value,
                f"商品汇总!M{row}",
            )
            product_url = _required_http_url(summary.cell(row, 14).value, f"商品汇总!N{row}")
            if _pdp_identity(product_url) != key:
                raise ValueError(f"PDP URL identity mismatch in 商品汇总!N{row}")
            products[key] = {
                "rank": rank,
                "page": page,
                "title": title,
                "product_url": product_url,
                "main_url": main_url,
                "expected_skus": expected_skus,
                "expected_secondary": expected_secondary,
            }
        if pages != set(range(1, max(pages) + 1)):
            raise ValueError(f"商品汇总 contains non-contiguous list pages: {sorted(pages)!r}")

        sku_per_product = {key: 0 for key in products}
        model_keys: set[tuple[str, str, str]] = set()
        for row in range(DATA_ROW, sku.max_row + 1):
            rank = _required_int(sku.cell(row, 1).value, f"SKU明细!A{row}", minimum=1)
            page = _required_int(sku.cell(row, 2).value, f"SKU明细!B{row}", minimum=1)
            shop_id = _required_text(sku.cell(row, 3).value, f"SKU明细!C{row}")
            item_id = _required_text(sku.cell(row, 4).value, f"SKU明细!D{row}")
            key = (shop_id, item_id)
            product = products.get(key)
            if product is None:
                raise ValueError(f"SKU明细 row {row} references an unknown product")
            if rank != product["rank"] or page != product["page"]:
                raise ValueError(f"SKU明细 row {row} has mismatched rank/page")
            if _required_text(sku.cell(row, 5).value, f"SKU明细!E{row}") != product["title"]:
                raise ValueError(f"SKU明细 row {row} has a mismatched title")
            model_id = _required_text(sku.cell(row, 6).value, f"SKU明细!F{row}")
            model_key = (shop_id, item_id, model_id)
            if not model_id.isdigit() or model_key in model_keys:
                raise ValueError(f"Invalid or duplicate model ID in SKU明细 row {row}")
            model_keys.add(model_key)
            _required_text(sku.cell(row, 7).value, f"SKU明细!G{row}")
            image_url = sku.cell(row, 8).value
            if image_url not in (None, ""):
                _required_http_url(image_url, f"SKU明细!H{row}")
            if _required_http_url(sku.cell(row, 9).value, f"SKU明细!I{row}") != product["product_url"]:
                raise ValueError(f"SKU明细 row {row} has a mismatched PDP URL")
            sku_per_product[key] += 1
        for key, product in products.items():
            if sku_per_product[key] != product["expected_skus"]:
                raise ValueError(f"SKU count mismatch for product {key!r}")

        main_urls: dict[tuple[str, str], list[str]] = {key: [] for key in products}
        secondary_indices: dict[tuple[str, str], list[int]] = {key: [] for key in products}
        secondary_count = 0
        for row in range(DATA_ROW, images.max_row + 1):
            rank = _required_int(images.cell(row, 1).value, f"图片明细!A{row}", minimum=1)
            page = _required_int(images.cell(row, 2).value, f"图片明细!B{row}", minimum=1)
            shop_id = _required_text(images.cell(row, 3).value, f"图片明细!C{row}")
            item_id = _required_text(images.cell(row, 4).value, f"图片明细!D{row}")
            key = (shop_id, item_id)
            product = products.get(key)
            if product is None:
                raise ValueError(f"图片明细 row {row} references an unknown product")
            if rank != product["rank"] or page != product["page"]:
                raise ValueError(f"图片明细 row {row} has mismatched rank/page")
            if _required_text(images.cell(row, 5).value, f"图片明细!E{row}") != product["title"]:
                raise ValueError(f"图片明细 row {row} has a mismatched title")
            image_type = images.cell(row, 6).value
            image_index = _required_int(images.cell(row, 7).value, f"图片明细!G{row}", minimum=1)
            image_url = _required_http_url(images.cell(row, 8).value, f"图片明细!H{row}")
            if _required_http_url(images.cell(row, 9).value, f"图片明细!I{row}") != product["product_url"]:
                raise ValueError(f"图片明细 row {row} has a mismatched PDP URL")
            if image_type == "主图":
                if image_index != 1:
                    raise ValueError(f"Main-image index must be 1 in 图片明细 row {row}")
                main_urls[key].append(image_url)
            elif image_type == "副图":
                secondary_count += 1
                secondary_indices[key].append(image_index)
            else:
                raise ValueError(f"Unknown image type in 图片明细!F{row}: {image_type!r}")
        for key, product in products.items():
            if main_urls[key] != [product["main_url"]]:
                raise ValueError(f"Main-image mismatch for product {key!r}")
            expected_indices = list(range(1, product["expected_secondary"] + 1))
            if sorted(secondary_indices[key]) != expected_indices:
                raise ValueError(f"Secondary-image sequence mismatch for product {key!r}")

        audit_values: dict[str, Any] = {}
        for row in range(DATA_ROW, audit.max_row + 1):
            label = _required_text(audit.cell(row, 1).value, f"抓取核验!A{row}")
            if label in audit_values:
                raise ValueError(f"Duplicate audit item: {label!r}")
            audit_values[label] = audit.cell(row, 2).value
        audit_status = str(audit.cell(row=3, column=2).value or "")
        if audit_status != "通过" or audit_values.get("完整性结论") != "通过":
            raise ValueError("Workbook audit status is not 通过")
        if audit_values.get("排序方式") != "Top Sales":
            raise ValueError("Workbook audit sort order is not Top Sales")
        _validate_store_url(audit_values.get("店铺 URL"))
        expected_audit_counts = {
            "列表总页数": max(pages),
            "唯一商品数": product_count,
            "成功进入详情页": product_count,
            "详情页失败数": 0,
            "未展示月销商品数": missing_monthly,
            "SKU 总数": sku_count,
            "有 SKU 的商品数": product_count,
            "主图数": product_count,
            "副图数": secondary_count,
            "无效图片 URL 数": 0,
        }
        for label, expected in expected_audit_counts.items():
            actual = _required_int(audit_values.get(label), f"抓取核验/{label}")
            if actual != expected:
                raise ValueError(
                    f"Audit count mismatch for {label!r}: expected {expected}, got {actual}"
                )
        occurrences = _required_int(audit_values.get("商品卡出现次数"), "抓取核验/商品卡出现次数", minimum=1)
        duplicates = _required_int(audit_values.get("跨页重复次数"), "抓取核验/跨页重复次数")
        if occurrences - duplicates != product_count:
            raise ValueError("Audit occurrence/de-duplication counts do not reconcile")
        optional_audit_counts = {
            "详情解析成功数": product_count,
            "详情解析错误数": 0,
            "无效商品 URL 数": 0,
        }
        for label, expected in optional_audit_counts.items():
            if label in audit_values and _required_int(audit_values[label], f"抓取核验/{label}") != expected:
                raise ValueError(f"Audit count mismatch for {label!r}")
        if "全店排名连续" in audit_values and audit_values["全店排名连续"] != "是":
            raise ValueError("Audit says product ranks are not contiguous")

        return WorkbookStats(
            product_count=product_count,
            sku_count=sku_count,
            main_image_count=product_count,
            secondary_image_count=secondary_count,
            audit_status=audit_status,
        )
    finally:
        wb.close()


def write_excel(result: Any, output_path: str | os.PathLike[str]) -> Path:
    """Write, reopen, verify and atomically publish one ``.xlsx`` workbook.

    No JSON, HTML, image preview or validation sidecar is created.  If either
    saving or validation fails, a pre-existing destination workbook is left
    untouched and the temporary file is removed.
    """

    destination = Path(output_path).expanduser()
    if destination.suffix.lower() != ".xlsx":
        raise ValueError(f"Excel output must use the .xlsx extension: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    view = _normalise_export(result)
    workbook, expected = _build_workbook(view)
    if expected.audit_status != "通过":
        workbook.close()
        raise ValueError("Scrape completeness validation failed; refusing to replace Excel")
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.stem}.",
            suffix=".xlsx",
        )
    except BaseException:
        workbook.close()
        raise
    temporary_path = Path(temporary_name)
    descriptor_open = True
    try:
        os.close(file_descriptor)
        descriptor_open = False
        try:
            workbook.save(temporary_path)
        finally:
            workbook.close()
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        _validate_with_expected(temporary_path, expected)
        os.replace(temporary_path, destination)
        try:
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Directory fsync is not available on every platform/filesystem.
            pass
        return destination
    except BaseException:
        if descriptor_open:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        temporary_path.unlink(missing_ok=True)
        raise
