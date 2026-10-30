"""中证 / 国证官方指数文件的只读适配器，只供教学对照。

来源名与文件入口（一次调用只使用其中一条，失败不改试别的地址）：

- provider ``csi``：中证指数有限公司，站点 csindex。
  成分 ``.../autofile/cons/{code}cons.xls``，
  收盘权重 ``.../autofile/closeweight/{code}closeweight.xls``，
  指数估值 ``.../autofile/indicator/{code}indicator.xls``
  （主机 ``oss-ch.csindex.com.cn``）。
- provider ``cni``：国证指数，站点 cnindex.com.cn。
  成分与权重共用样本导出 ``/sample-detail/download?indexcode={code}``，
  各自只读自己的列，不是把两家网站拼成一条序列。
  估值使用 ``/docs/gz_{code}indicator.xls``。这条按官网 docs 目录的常见
  文件命名写下，不保证当前仍可下载；维护者打开联网前要复核。

用途：查看调用方指定的一只指数在官方文件里的成分、权重或指数层面估值列
（成分数量、权重原值、文件日期）。不产生买卖建议，不解释贵贱，不做个股估值筛选，
也不替代同花顺日 K。

条款：这些官方文件的再分发和商用许可尚未审完（许可待审）。本程序的开源许可
不含文件再分发权。维护者在把 ``allow_network`` 设为 True、缓存结果或放进发行包之前，
需要自行复核官网条款，并确认路径仍然是官方文件。

默认 ``allow_network=False``。未提供 ``fetch_bytes`` 时返回显式缺口，不打开网络。
官方 xls 若实际是 HTML 表格或 CSV/TSV，用标准库解析；二进制 xls/xlsx 在零依赖
环境里只记缺口，不安装、不调用可选表格包。

返回字典始终包含 ``source``、``provider``、``index_code``、``as_of``、``items``、
``gaps``、``notes``、``license_note``，并额外带 ``kind``（constituents / weights /
valuation）。``license_note`` 非空。权重和估值的空单元格不会写成 0。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

CSI_CONSTITUENTS_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/{code}cons.xls"
CSI_WEIGHTS_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/{code}closeweight.xls"
CSI_VALUATION_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls"
CNI_SAMPLE_URL = "https://www.cnindex.com.cn/sample-detail/download?indexcode={code}"
CNI_VALUATION_URL = "https://www.cnindex.com.cn/docs/gz_{code}indicator.xls"

_URLS = {
    ("csi", "constituents"): CSI_CONSTITUENTS_URL,
    ("csi", "weights"): CSI_WEIGHTS_URL,
    ("csi", "valuation"): CSI_VALUATION_URL,
    ("cni", "constituents"): CNI_SAMPLE_URL,
    ("cni", "weights"): CNI_SAMPLE_URL,
    ("cni", "valuation"): CNI_VALUATION_URL,
}

LICENSE_NOTE = (
    "中证指数（csindex）与国证指数（cnindex）官方文件的再分发和商用条款尚未审完（许可待审）。"
    "本程序许可不含这些成分、权重或估值文件的再分发权。"
    "维护者复核官网条款与下载路径之前，不要把取回的文件写入发行包，也不要当作投资依据。"
)
TEACHING_NOTE = "指数点位与估值字段用于教学对照，不是买卖建议。"
NO_MIX_NOTE = "只读取所选官方文件这一条路径，不与同花顺或其他来源拼接。"

_MAX_BYTES = 8_000_000
_MAX_GAPS = 50
_KINDS = ("constituents", "weights", "valuation")
_VALUATION_KEYS = ("pe1", "pe2", "dividend_yield1", "dividend_yield2", "pb")
_MISSING = {"", "-", "--", "—", "–", "na", "n/a", "null", "none", "nan"}
_HEADER_UNITS = ("(倍)", "(%)", "%", "(元)")
_DATE_LINE = re.compile(r"(?:截止日期|数据日期)\s*[:：]\s*(\d{4}[-/.]?\d{2}[-/.]?\d{2}|\d{8})")

_CODE_ALIASES = ("成分券代码", "成份券代码", "证券代码", "股票代码", "样本代码", "样本券代码", "constituentcode", "securitycode", "stockcode", "code")
_INDEX_ALIASES = ("指数代码", "indexcode")
_NAME_ALIASES = ("成分券名称", "成份券名称", "证券简称", "证券名称", "股票简称", "股票名称", "样本简称", "样本名称", "constituentname", "name")
_EXCHANGE_ALIASES = ("交易所", "交易所名称", "市场", "exchange")
_DATE_ALIASES = ("日期", "生效日期", "数据日期", "交易日期", "date", "tradedate")
_WEIGHT_ALIASES = ("权重", "权重(%)", "个股权重", "权重比例", "weight", "weight(%)", "weightpct")
_PE1_ALIASES = ("市盈率1", "市盈率１", "pe1")
_PE2_ALIASES = ("市盈率2", "市盈率２", "pe2")
_DY1_ALIASES = ("股息率1", "股息率１", "dp1", "dividendyield1")
_DY2_ALIASES = ("股息率2", "股息率２", "dp2", "dividendyield2")
_PB_ALIASES = ("市净率", "市净率1", "pb", "pb1")
_BARE_PE = ("市盈率", "pe")
_BARE_DY = ("股息率", "dividendyield")
_ASSIGN = (
    ("index_code", _INDEX_ALIASES),
    ("code", _CODE_ALIASES),
    ("name", _NAME_ALIASES),
    ("exchange", _EXCHANGE_ALIASES),
    ("date", _DATE_ALIASES),
    ("weight", _WEIGHT_ALIASES),
    ("pe1", _PE1_ALIASES),
    ("pe2", _PE2_ALIASES),
    ("dividend_yield1", _DY1_ALIASES),
    ("dividend_yield2", _DY2_ALIASES),
    ("pb", _PB_ALIASES),
)


def fetch_constituents(index_code, *, provider="csi", allow_network=False, fetch_bytes=None):
    """读取指数成分。``allow_network`` 默认关闭；测试应传入合成文件字节。"""
    return _fetch(index_code, kind="constituents", provider=provider, allow_network=allow_network, fetch_bytes=fetch_bytes)


def fetch_weights(index_code, *, provider="csi", allow_network=False, fetch_bytes=None):
    """读取指数权重。空单元格不会写成 0，缺权重列则不返回权重行。"""
    return _fetch(index_code, kind="weights", provider=provider, allow_network=allow_network, fetch_bytes=fetch_bytes)


def fetch_valuation(index_code, *, provider="csi", allow_network=False, fetch_bytes=None):
    """读取指数层面的估值列。不解释贵贱，也不把逐只证券的估值列成清单。"""
    return _fetch(index_code, kind="valuation", provider=provider, allow_network=allow_network, fetch_bytes=fetch_bytes)


def official_file_url(provider, kind, index_code):
    """返回这一条官方文件入口。代码或 provider 无效时返回 None，不访问网络。"""
    provider_norm = _provider(provider)
    code = _normalize_index_code(index_code)
    if provider_norm is None or kind not in _KINDS or code is None:
        return None
    return _URLS[(provider_norm, kind)].format(code=code)


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """只跟随官方文件主机自己的重定向，不跳到其他站点。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        current = urllib.parse.urlparse(req.full_url).netloc
        target = urllib.parse.urlparse(newurl).netloc
        if target != current:
            raise urllib.error.URLError("官方文件重定向到了其他站点，已停止")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HTMLTables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        if name == "table" and self._table is None:
            self._table = []
        elif name == "tr" and self._table is not None:
            self._row = []
        elif name in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        name = tag.lower()
        if name in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).replace("\xa0", " ").strip())
            self._cell = None
        elif name == "tr" and self._row is not None and self._table is not None:
            if any(cell.strip() for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif name == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _fetch(index_code, *, kind, provider, allow_network, fetch_bytes):
    notes = [TEACHING_NOTE, NO_MIX_NOTE]
    provider_norm = _provider(provider)
    if provider_norm is None:
        return _envelope("", "", "", None, [], ["provider 只能是 csi（中证）或 cni（国证），未访问网络。"], notes, kind)
    source = "csindex" if provider_norm == "csi" else "cnindex"
    code = _normalize_index_code(index_code)
    if code is None:
        return _envelope(source, provider_norm, "", None, [], ["指数代码无效。只接受 4 至 12 位字母数字（可带 .SH/.SZ/.BJ/.CSI/.CNI 后缀），未访问网络。"], notes, kind)
    if isinstance(index_code, str) and index_code.strip().upper() != code:
        notes.append(f"已将请求代码规范为 {code}。")
    url = _URLS[(provider_norm, kind)].format(code=code)
    notes.append(f"官方文件路径：{url}。")
    if provider_norm == "cni" and kind in {"constituents", "weights"}:
        notes.append("国证成分与权重读取同一条样本文件路径上的不同列，不与中证文件合并。")
    if provider_norm == "cni" and kind == "valuation":
        notes.append("国证估值文件路径需维护者复核是否仍为官网文件；失效时不改读中证 indicator，也不改读行情接口。")
    if not isinstance(allow_network, bool):
        return _envelope(source, provider_norm, code, None, [], ["allow_network 必须是布尔值，未访问网络。"], notes, kind)
    payload, load_gaps, origin = _load(url, allow_network=allow_network, fetch_bytes=fetch_bytes)
    notes.append(origin)
    if payload is None:
        return _envelope(source, provider_norm, code, None, [], load_gaps, notes, kind)
    parsed = _parse_payload(payload, kind=kind, index_code=code, url=url)
    return _envelope(source, provider_norm, code, parsed["as_of"], parsed["items"], load_gaps + parsed["gaps"], notes + parsed["notes"], kind)


def _provider(value):
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in {"csi", "cni"} else None


def _normalize_index_code(value):
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    for suffix in (".SH", ".SZ", ".BJ", ".CSI", ".CNI"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    if len(text) > 2 and text[:2] in {"SH", "SZ"} and re.fullmatch(r"[A-Z0-9]{4,12}", text[2:]):
        text = text[2:]
    if re.fullmatch(r"[A-Z0-9]{4,12}", text):
        return text
    return None


def _load(url, *, allow_network, fetch_bytes):
    if fetch_bytes is not None:
        if not isinstance(fetch_bytes, (bytes, bytearray)):
            return None, ["fetch_bytes 必须是字节，未解析，也未访问网络。"], "未访问网络。"
        if len(fetch_bytes) > _MAX_BYTES:
            return None, [f"文件超过 {_MAX_BYTES} 字节，已停止解析。未改试其他来源。"], "使用调用方提供的文件字节，未访问网络。"
        if len(fetch_bytes) == 0:
            return None, ["文件为空。未改试其他来源。"], "使用调用方提供的文件字节，未访问网络。"
        return bytes(fetch_bytes), [], "使用调用方提供的文件字节，未访问网络。"
    if not allow_network:
        return None, ["未读取官网文件：allow_network=False，且未提供 fetch_bytes。"], "未访问网络。"
    try:
        payload = _http_get(url)
    except Exception as exc:
        reason = _public_error(exc)
        return None, [f"读取官网文件失败（{reason}）。试过的路径：{url}。未改试其他来源。"], "已按上面的官方文件路径请求一次。"
    if len(payload) > _MAX_BYTES:
        return None, [f"官网文件超过 {_MAX_BYTES} 字节，已停止解析。试过的路径：{url}。未改试其他来源。"], "已按上面的官方文件路径请求一次。"
    if not payload:
        return None, [f"官网文件为空。试过的路径：{url}。未改试其他来源。"], "已按上面的官方文件路径请求一次。"
    return payload, [], "已按上面的官方文件路径请求一次。"


def _http_get(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CandleAtlasTeaching/1.0 (official index file; offline by default)"},
        method="GET",
    )
    opener = urllib.request.build_opener(_SameHostRedirect)
    with opener.open(request, timeout=20) as response:
        return response.read(_MAX_BYTES + 1)


def _public_error(exc):
    text = " ".join(str(exc).split())
    text = re.sub(r"(?:[A-Za-z]:)?(?:/|\\)[^\s]+", "[path]", text)
    if len(text) > 160:
        text = text[:160] + "…"
    return f"{type(exc).__name__}: {text}"


def _parse_payload(payload, *, kind, index_code, url):
    binary = _binary_kind(payload)
    if binary:
        return {"items": [], "as_of": None, "gaps": [f"文件是二进制表格（{binary}），默认零依赖环境不解析。官方文件路径：{url}。未改用其他来源。"], "notes": []}
    try:
        text = _decode(payload)
    except UnicodeError:
        return {"items": [], "as_of": None, "gaps": ["文件无法按 UTF-8、UTF-16 或 GB18030 解码。未改试其他来源。"], "notes": []}
    try:
        tables, layout = _tables_from_text(text)
    except csv.Error as exc:
        reason = _public_error(exc)
        return {
            "items": [],
            "as_of": None,
            "gaps": [f"CSV 解析失败（{reason}）。官方文件路径：{url}。未改试其他来源。"],
            "notes": [],
        }
    if layout == "html" and not tables:
        return {"items": [], "as_of": None, "gaps": ["文件像 HTML，但没有可读取的表格。未改试其他来源。"], "notes": []}
    if not tables:
        return {"items": [], "as_of": None, "gaps": ["文件不是可解析的 CSV/TSV 或 HTML 表格。未按其他接口另行请求。"], "notes": []}
    best = None
    for table in tables:
        parsed = _parse_table(table, kind=kind, index_code=index_code)
        score = (0 if parsed["gaps"] and not parsed["items"] else 1, len(parsed["items"]))
        if best is None or score > best[0]:
            best = (score, parsed)
    return best[1]


def _binary_kind(payload):
    if payload.startswith(b"PK\x03\x04"):
        return "xlsx"
    if payload.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    return None


def _decode(payload):
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError("undecodable")


def _tables_from_text(text):
    sample = text.lstrip("\ufeff")
    if "<table" in sample[:8000].lower():
        parser = _HTMLTables()
        try:
            parser.feed(sample)
            parser.close()
        except Exception:
            return [], "html"
        return parser.tables, "html"
    rows = _csv_rows(sample)
    return ([rows] if rows else []), "csv"


def _csv_rows(text):
    probe = "\n".join(line for line in text.splitlines()[:20] if line.strip())
    if probe.count("\t") > probe.count(","):
        delimiter = "\t"
    elif probe.count(";") > probe.count(",") and "," not in probe:
        delimiter = ";"
    else:
        delimiter = ","
    previous_limit = csv.field_size_limit()
    try:
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    finally:
        csv.field_size_limit(previous_limit)


def _parse_table(rows, *, kind, index_code):
    header_at = _find_header(rows)
    if header_at is None:
        return {"items": [], "as_of": None, "gaps": ["未识别表头（需要成分代码、权重或估值列）。未改试其他来源。"], "notes": []}
    columns = _map_columns(rows[header_at])
    gaps = []
    if kind in {"constituents", "weights"} and "code" not in columns:
        gaps.append("缺少成分代码列，未把其他列当成成分。")
    if kind == "weights" and "weight" not in columns:
        gaps.append("缺少权重列。空权重不会记为 0，没有权重列则不返回权重。")
    if kind == "valuation" and "code" in columns:
        gaps.append("文件含证券代码列。本模块不提供个股估值筛选，未返回逐只证券的估值。")
    elif kind == "valuation" and not any(key in columns for key in _VALUATION_KEYS):
        gaps.append("缺少估值列（市盈率、市净率或股息率）。空单元格不会记为 0。")
    if gaps:
        return {"items": [], "as_of": None, "gaps": gaps, "notes": []}
    items = []
    notes = []
    accepted = {}
    conflicted = set()
    if "index_code" not in columns and kind in {"constituents", "weights"}:
        notes.append("文件没有指数代码列，未能与请求代码交叉核对。")
    weight_header = rows[header_at][columns["weight"]] if "weight" in columns else ""
    header_percent = "%" in _norm_header(weight_header)
    for offset, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        if not any(cell.strip() for cell in row) or _same_header(row, rows[header_at]):
            continue
        number = offset
        if "index_code" in columns:
            raw_index = _cell(row, columns["index_code"])
            got = _normalize_index_code(raw_index) if raw_index else None
            if got != index_code:
                label = got or (raw_index[:32] if raw_index else "空")
                gaps.append(f"第 {number} 行指数代码为 {label}，与请求的 {index_code} 不一致，已跳过。")
                continue
        if kind == "valuation":
            item, row_gaps = _valuation_item(row, columns, number)
        elif kind == "weights":
            item, row_gaps = _weight_item(row, columns, number, header_percent)
        else:
            item, row_gaps = _constituent_item(row, columns, number)
        gaps.extend(row_gaps)
        if item:
            _remember_item(kind, item, number, items, accepted, conflicted, gaps)
    items = [item for item in items if item is not None]
    as_of, as_of_notes, as_of_gaps = _as_of(items, rows[:header_at], "date" in columns)
    return {"items": items, "as_of": as_of, "gaps": gaps + as_of_gaps, "notes": notes + as_of_notes}


def _constituent_item(row, columns, number):
    code = _security_code(_cell(row, columns["code"]))
    if not code:
        return None, [f"第 {number} 行成分代码为空或无法识别，已跳过。"]
    item = {"code": code}
    parsed_date, date_state = _optional_date(row, columns)
    if date_state == "bad":
        return None, [f"第 {number} 行日期无法识别，已跳过。"]
    gaps = []
    if date_state == "missing":
        gaps.append(f"第 {number} 行日期为空或未知。")
    if parsed_date:
        item["date"] = parsed_date
    name = _cell(row, columns.get("name"))
    exchange = _cell(row, columns.get("exchange"))
    if name:
        item["name"] = name
    if exchange:
        item["exchange"] = exchange
    return item, gaps


def _weight_item(row, columns, number, header_percent):
    code = _security_code(_cell(row, columns["code"]))
    if not code:
        return None, [f"第 {number} 行成分代码为空或无法识别，已跳过。"]
    number_value, state, cell_percent = _parse_number(_cell(row, columns["weight"]))
    if state == "empty":
        return None, [f"第 {number} 行权重为空，未记为 0。"]
    if state != "ok":
        return None, [f"第 {number} 行权重无法解析，未记为 0。"]
    item = {"code": code, "weight": number_value, "weight_unit": "percent" if header_percent or cell_percent else "file"}
    parsed_date, date_state = _optional_date(row, columns)
    if date_state == "bad":
        return None, [f"第 {number} 行日期无法识别，已跳过。"]
    gaps = []
    if date_state == "missing":
        gaps.append(f"第 {number} 行日期为空或未知。")
    if parsed_date:
        item["date"] = parsed_date
    name = _cell(row, columns.get("name"))
    if name:
        item["name"] = name
    return item, gaps


def _valuation_item(row, columns, number):
    parsed_date, date_state = _optional_date(row, columns)
    if date_state == "bad":
        return None, [f"第 {number} 行日期无法识别，已跳过。"]
    fields = {}
    saw_empty = False
    saw_bad = False
    for key in _VALUATION_KEYS:
        if key not in columns:
            continue
        number_value, state, _percent = _parse_number(_cell(row, columns[key]))
        if state == "ok":
            fields[key] = number_value
        elif state == "empty":
            saw_empty = True
        else:
            saw_bad = True
    if not fields:
        if saw_bad:
            return None, [f"第 {number} 行估值无法解析，未记为 0。"]
        return None, [f"第 {number} 行估值列为空，未记为 0。"]
    gaps = []
    if date_state == "missing":
        gaps.append(f"第 {number} 行日期为空或未知。")
    if saw_empty or saw_bad:
        gaps.append(f"第 {number} 行部分估值列为空或无法解析，未把这些空列记为 0。")
    item = dict(fields)
    if parsed_date:
        item = {"date": parsed_date, **item}
    return item, gaps


def _optional_date(row, columns):
    if "date" not in columns:
        return None, "absent"
    raw = _cell(row, columns["date"])
    if not raw or raw.lower() in _MISSING:
        return None, "missing"
    parsed = _parse_date(raw)
    if parsed is None:
        return None, "bad"
    return parsed, "ok"


def _as_of(items, preamble_rows, has_date_column):
    notes = []
    gaps = []
    dates = sorted({item["date"] for item in items if item.get("date")})
    undated = any(not item.get("date") for item in items)
    preamble = _preamble_as_of(preamble_rows)
    if dates:
        if len(dates) > 1:
            notes.append(f"文件含多个日期（{dates[0]} 至 {dates[-1]}），as_of 取最晚一日，未与其他来源合并。")
        if preamble and preamble != dates[-1]:
            notes.append("表前截止日期与行内日期不一致，as_of 以行内日期为准。")
        if undated and has_date_column:
            gaps.append("as_of 仅覆盖有日期的行，部分行日期为空或未知。")
        return dates[-1], notes, gaps
    if preamble and items:
        if has_date_column:
            notes.append("as_of 取自文件中的截止日期行；日期列存在但行内没有可读取的日期。")
        else:
            notes.append("as_of 取自文件中的截止日期行，表内没有逐行日期。")
        return preamble, notes, gaps
    if not items:
        return None, notes, gaps
    if not has_date_column:
        gaps.append("文件未提供日期列，as_of 为空。")
    else:
        gaps.append("没有可读取的日期，as_of 为空。")
    return None, notes, gaps


def _row_identity(kind, item):
    date = item.get("date")
    if not date:
        return None
    if kind == "valuation":
        return (date,)
    return (date, item.get("code"))


def _row_signature(kind, item):
    if kind == "valuation":
        return tuple(item.get(key) for key in _VALUATION_KEYS)
    if kind == "weights":
        return (item.get("code"), item.get("weight"), item.get("weight_unit"), item.get("name"))
    return (item.get("code"), item.get("name"), item.get("exchange"))


def _conflict_gap(kind, number, item, previous):
    date = item.get("date")
    code = item.get("code")
    if previous is None:
        if kind == "valuation":
            return f"第 {number} 行与已有记录同一日期（{date}）估值冲突，未采用。"
        return f"第 {number} 行与已有记录同一日期（{date}）同一证券（{code}）冲突，未采用。"
    if kind == "valuation":
        return f"第 {number} 行与第 {previous} 行同一日期（{date}）估值冲突，均未采用。"
    return f"第 {number} 行与第 {previous} 行同一日期（{date}）同一证券（{code}）冲突，均未采用。"


def _remember_item(kind, item, number, items, accepted, conflicted, gaps):
    identity = _row_identity(kind, item)
    if identity is None:
        items.append(item)
        return
    signature = _row_signature(kind, item)
    if identity in conflicted:
        gaps.append(_conflict_gap(kind, number, item, None))
        return
    previous = accepted.get(identity)
    if previous is not None:
        prev_index, prev_number, prev_sig = previous
        if prev_sig == signature:
            return
        items[prev_index] = None
        del accepted[identity]
        conflicted.add(identity)
        gaps.append(_conflict_gap(kind, number, item, prev_number))
        return
    accepted[identity] = (len(items), number, signature)
    items.append(item)


def _preamble_as_of(rows):
    for row in rows:
        match = _DATE_LINE.search(" ".join(row))
        if match:
            return _parse_date(match.group(1))
    return None


def _find_header(rows):
    recognized = _recognized_headers()
    best = None
    for index, row in enumerate(rows[:40]):
        hits = sum(1 for cell in row if _matches_any(_norm_header(cell), recognized))
        if hits >= 2 and (best is None or hits > best[0]):
            best = (hits, index)
    return None if best is None else best[1]


def _recognized_headers():
    names = set()
    for _key, aliases in _ASSIGN:
        names.update(_norm_header(alias) for alias in aliases)
    names.update(_norm_header(alias) for alias in _BARE_PE + _BARE_DY)
    return names


def _map_columns(header):
    columns = {}
    used = set()
    for key, aliases in _ASSIGN:
        found = _find_alias(header, aliases, used)
        if found is None:
            continue
        columns[key] = found
        used.add(found)
    if "pe1" not in columns:
        found = _find_alias(header, _BARE_PE, used)
        if found is not None:
            columns["pe1"] = found
            used.add(found)
    if "dividend_yield1" not in columns:
        found = _find_alias(header, _BARE_DY, used)
        if found is not None:
            columns["dividend_yield1"] = found
    return columns


def _find_alias(header, aliases, used):
    normalized = [_norm_header(alias) for alias in aliases]
    for index, cell in enumerate(header):
        if index in used:
            continue
        if _matches_any(_norm_header(cell), normalized):
            return index
    return None


def _matches_any(cell, aliases):
    for alias in aliases:
        if cell == alias or any(cell == alias + unit for unit in _HEADER_UNITS):
            return True
    return False


def _norm_header(value):
    text = (value or "").strip().lower()
    text = text.replace("\u3000", "").replace(" ", "").replace("_", "")
    text = text.replace("（", "(").replace("）", ")").replace("％", "%")
    return text


def _same_header(row, header):
    left = [_norm_header(cell) for cell in row]
    right = [_norm_header(cell) for cell in header]
    return left == right


def _cell(row, index):
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _security_code(value):
    return _normalize_index_code(value)


def _parse_date(value):
    text = (value or "").strip()
    if not text or text.lower() in _MISSING:
        return None
    text = text.split()[0].replace(".", "-").replace("/", "-")
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _parse_number(value):
    text = (value or "").strip().replace(",", "").replace("％", "%")
    if text.lower() in _MISSING:
        return None, "empty", False
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return None, "bad", percent
    if number != number or number in {float("inf"), float("-inf")}:
        return None, "bad", percent
    return number, "ok", percent


def _envelope(source, provider, index_code, as_of, items, gaps, notes, kind):
    return {
        "source": source,
        "provider": provider,
        "index_code": index_code,
        "as_of": as_of,
        "items": items,
        "gaps": _cap(gaps),
        "notes": _unique(notes),
        "license_note": LICENSE_NOTE,
        "kind": kind,
    }


def _cap(gaps):
    if len(gaps) <= _MAX_GAPS:
        return list(gaps)
    hidden = len(gaps) - _MAX_GAPS
    return list(gaps[:_MAX_GAPS]) + [f"另有 {hidden} 条缺口未逐条列出。"]


def _unique(notes):
    seen = set()
    result = []
    for note in notes:
        if note and note not in seen:
            seen.add(note)
            result.append(note)
    return result
