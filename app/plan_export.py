from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape


PLAN_HEADERS = [
    "순번",
    "구분",
    "일자",
    "요일",
    "교시",
    "학반",
    "과목",
    "원 담당 교사",
    "보강/교체 교사",
    "내용",
    "비고",
]

WEEKDAY_PERIODS = [
    ("월", 7),
    ("화", 7),
    ("수", 7),
    ("목", 7),
    ("금", 6),
]


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(ref: str, value: object, style: int = 0) -> str:
    text = escape("" if value is None else str(value))
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _row(index: int, values: list[object], style: int = 0, height: int | None = None) -> str:
    height_attr = f' ht="{height}" customHeight="1"' if height else ""
    cells = "".join(_cell(f"{_column_name(col)}{index}", value, style) for col, value in enumerate(values, start=1))
    return f'<row r="{index}"{height_attr}>{cells}</row>'


def _styled_row(index: int, values: list[tuple[object, int]], height: int | None = None) -> str:
    height_attr = f' ht="{height}" customHeight="1"' if height else ""
    cells = "".join(
        _cell(f"{_column_name(col)}{index}", value, style) for col, (value, style) in enumerate(values, start=1)
    )
    return f'<row r="{index}"{height_attr}>{cells}</row>'


def _slot_label(cell: dict | None) -> str:
    if not cell:
        return "공강"
    status = cell.get("status") or cell.get("slot_type") or "free"
    effective = cell.get("effective")
    original = cell.get("original")
    if status == "holiday":
        return cell.get("label") or "수업 없음"
    if status == "free":
        return "공강"
    if status == "travel" and effective:
        return f"{effective.get('location_label') or '순회'}\n순회"
    if status == "class" and effective:
        return f"{effective.get('class_code') or ''} {effective.get('subject') or ''}".strip()
    if status == "swapped-in" and effective:
        text = f"교체\n{effective.get('class_code') or ''} {effective.get('subject') or ''}".strip()
        if effective.get("from_teacher_name"):
            text += f"\n원 담당: {effective['from_teacher_name']}"
        return text
    if status == "swapped-out" and original:
        text = f"교체됨\n{original.get('class_code') or ''} {original.get('subject') or ''}".strip()
        if original.get("swap_with_name"):
            text += f"\n상대: {original['swap_with_name']}"
        return text
    if status in {"coverage-in", "coverage-pending-in"} and effective:
        text = f"보강\n{effective.get('class_code') or ''} {effective.get('subject') or ''}".strip()
        if effective.get("from_teacher_name"):
            text += f"\n원 담당: {effective['from_teacher_name']}"
        return text
    if status in {"coverage-out", "coverage-pending-out"} and original:
        text = f"보강 배정\n{original.get('class_code') or ''} {original.get('subject') or ''}".strip()
        if original.get("covered_by_name"):
            text += f"\n담당: {original['covered_by_name']}"
        return text
    return "공강"


def _slot_style(cell: dict | None) -> int:
    if not cell:
        return 5
    status = cell.get("status") or cell.get("slot_type") or "free"
    if status == "holiday":
        return 9
    if status == "free":
        return 5
    if status == "travel":
        return 10
    if status == "swapped-in":
        return 7
    if status == "swapped-out":
        return 11
    if status in {"coverage-in", "coverage-out", "coverage-pending-in", "coverage-pending-out"}:
        return 8
    return 6


def build_school_weekly_timetable_xlsx(weekly: dict) -> bytes:
    day_header_values: list[tuple[object, int]] = [("교사", 3)]
    period_header_values: list[tuple[object, int]] = [("", 3)]
    merges = ["A1:AI1", "A2:AI2", "A4:A5"]
    start_col = 2
    for day, (_label, period_count) in zip(weekly["days"], WEEKDAY_PERIODS):
        end_col = start_col + period_count - 1
        day_title = f"{day['day_label']} {str(day['date'])[5:].replace('-', '.')}"
        if not day.get("is_school_day", True):
            day_title += f"\n{day.get('label') or '수업 없음'}"
        day_header_values.extend([(day_title, 3)] + [("", 3) for _ in range(period_count - 1)])
        period_header_values.extend([(f"{period}교시", 3) for period in range(1, period_count + 1)])
        merges.append(f"{_column_name(start_col)}4:{_column_name(end_col)}4")
        start_col = end_col + 1

    rows = [
        _row(1, ["주간 전체 시간표(반영본)"], 1, 30),
        _row(2, [f"기간: {weekly['week_start']} ~ {weekly['week_end']} · 생성: {weekly.get('generated_at') or ''}"], 2, 22),
        _styled_row(4, day_header_values, 26),
        _styled_row(5, period_header_values, 22),
    ]

    for row_index, teacher in enumerate(weekly.get("teachers", []), start=6):
        values: list[tuple[object, int]] = [(teacher["teacher_name"], 4)]
        for day in teacher["days"]:
            periods_by_number = {cell["period"]: cell for cell in day.get("periods", [])}
            limit = 6 if day["weekday"] == 4 else 7
            for period in range(1, limit + 1):
                if not day.get("is_school_day", True):
                    values.append((day.get("label") or "수업 없음", 9))
                    continue
                cell = periods_by_number.get(period)
                values.append((_slot_label(cell), _slot_style(cell)))
        rows.append(_styled_row(row_index, values, 48))

    if not weekly.get("teachers"):
        rows.append(_styled_row(6, [("등록된 교사 계정이 없습니다.", 4)], 28))

    worksheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="16" customWidth="1"/>
    <col min="2" max="35" width="15" customWidth="1"/>
  </cols>
  <sheetData>
    {''.join(rows)}
  </sheetData>
  <mergeCells count="{len(merges)}">
    {''.join(f'<mergeCell ref="{ref}"/>' for ref in merges)}
  </mergeCells>
</worksheet>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="주간전체시간표" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="6">
    <font><sz val="10"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="16"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="10"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="맑은 고딕"/></font>
    <font><sz val="9"/><color rgb="FF475569"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="10"/><color rgb="FFB91C1C"/><name val="맑은 고딕"/></font>
  </fonts>
  <fills count="9">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF053F39"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE7F8F3"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDBEAFE"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFEDD5"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFEE2E2"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="12">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="3" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="4" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="4" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="8" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="5" fillId="8" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  </cellXfs>
</styleSheet>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        archive.writestr("xl/styles.xml", styles)
    return buffer.getvalue()


def build_plan_xlsx(plan: dict) -> bytes:
    rows = [
        _row(1, ["2026학년도 수업교체 및 보강계획서"], 1, 28),
        _row(2, [f"기간: {plan['week_start']} ~ {plan['week_end']}"], 2),
        _row(3, [f"작성일: {plan['generated_at']}"], 2),
        _row(5, PLAN_HEADERS, 3),
    ]
    for row_index, item in enumerate(plan["items"], start=6):
        rows.append(
            _row(
                row_index,
                [
                    item["sequence"],
                    item["type"],
                    item["date"],
                    item["day_label"],
                    f"{item['period']}교시",
                    item["class_code"],
                    item["subject"],
                    item["original_teacher_name"],
                    item["assigned_teacher_name"],
                    item["detail"],
                    item["note"],
                ],
                4,
                24,
            )
        )
    if not plan["items"]:
        rows.append(_row(6, ["", "해당 주의 확정된 교체·보강 내역이 없습니다."], 4, 24))

    worksheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <cols>
    <col min="1" max="1" width="8" customWidth="1"/>
    <col min="2" max="2" width="10" customWidth="1"/>
    <col min="3" max="3" width="14" customWidth="1"/>
    <col min="4" max="4" width="8" customWidth="1"/>
    <col min="5" max="5" width="10" customWidth="1"/>
    <col min="6" max="7" width="12" customWidth="1"/>
    <col min="8" max="9" width="16" customWidth="1"/>
    <col min="10" max="10" width="34" customWidth="1"/>
    <col min="11" max="11" width="24" customWidth="1"/>
  </cols>
  <sheetData>
    {''.join(rows)}
  </sheetData>
  <mergeCells count="3">
    <mergeCell ref="A1:K1"/>
    <mergeCell ref="A2:K2"/>
    <mergeCell ref="A3:K3"/>
  </mergeCells>
</worksheet>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="결보강계획서" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="11"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="16"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="11"/><name val="맑은 고딕"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="맑은 고딕"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF15324C"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="5">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="3" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
  </cellXfs>
</styleSheet>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        archive.writestr("xl/styles.xml", styles)
    return buffer.getvalue()


def _pdf_hex(value: object) -> str:
    return "<" + str(value).encode("utf-16-be").hex().upper() + ">"


def _shorten(value: object, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else f"{text[: max(0, limit - 1)]}…"


def _pdf_text(x: float, y: float, size: int, value: object, color: str = "0.07 0.12 0.12") -> str:
    return f"{color} rg\nBT /F1 {size} Tf {x:.1f} {y:.1f} Td {_pdf_hex(value)} Tj ET\n"


def _pdf_stream_object(stream: str) -> str:
    raw = stream.encode("ascii")
    return f"<< /Length {len(raw)} >>\nstream\n{stream}endstream"


def _build_pdf_content(plan: dict, rows: list[dict], page_number: int, page_count: int) -> str:
    width = 842
    height = 595
    left = 32
    top = 542
    row_h = 24
    columns = [
        ("순번", 34, lambda item: item.get("sequence", "")),
        ("구분", 44, lambda item: item["type"]),
        ("일자", 78, lambda item: item["date"]),
        ("요일", 42, lambda item: item["day_label"]),
        ("교시", 46, lambda item: f"{item['period']}교시"),
        ("학반", 54, lambda item: item["class_code"]),
        ("과목", 58, lambda item: item["subject"]),
        ("원 담당", 78, lambda item: item["original_teacher_name"]),
        ("보강/교체", 84, lambda item: item["assigned_teacher_name"]),
        ("내용", 178, lambda item: item["detail"]),
        ("비고", 86, lambda item: item["note"]),
    ]
    table_width = sum(col[1] for col in columns)
    content = [
        "q\n",
        "0.09 0.20 0.30 rg 0 560 842 35 re f\n",
        "Q\n",
        _pdf_text(left, 572, 16, "2026학년도 수업교체 및 보강계획서", "1 1 1"),
        _pdf_text(left, 548, 10, f"기간: {plan['week_start']} ~ {plan['week_end']}"),
        _pdf_text(left + 230, 548, 10, f"작성일: {plan['generated_at']}"),
        _pdf_text(width - 110, 548, 9, f"{page_number} / {page_count}"),
        "0.82 0.88 0.92 rg ",
        f"{left} {top - row_h + 4} {table_width} {row_h} re f\n",
        "0.15 0.20 0.24 RG 0.5 w\n",
    ]

    x = left
    for title, col_width, _getter in columns:
        content.append(f"{x:.1f} {top - row_h + 4:.1f} {col_width:.1f} {row_h:.1f} re S\n")
        content.append(_pdf_text(x + 4, top - 12, 8, title))
        x += col_width

    if not rows:
        y = top - (row_h * 2)
        content.append(f"{left:.1f} {y:.1f} {table_width:.1f} {row_h:.1f} re S\n")
        content.append(_pdf_text(left + 12, y + 8, 9, "해당 주의 확정된 교체·보강 내역이 없습니다."))
    else:
        for row_index, item in enumerate(rows, start=1):
            y = top - row_h * (row_index + 1) + 4
            x = left
            is_cancelled_swap_class = item.get("type") == "교체"
            if is_cancelled_swap_class:
                content.append("1.00 0.95 0.95 rg ")
                content.append(f"{left:.1f} {y:.1f} {table_width:.1f} {row_h:.1f} re f\n")
                content.append("0.15 0.20 0.24 RG\n")
            elif row_index % 2 == 0:
                content.append("0.96 0.98 0.99 rg ")
                content.append(f"{left:.1f} {y:.1f} {table_width:.1f} {row_h:.1f} re f\n")
                content.append("0.15 0.20 0.24 RG\n")
            for _title, col_width, getter in columns:
                content.append(f"{x:.1f} {y:.1f} {col_width:.1f} {row_h:.1f} re S\n")
                max_chars = max(3, int(col_width / 8))
                text_color = "0.73 0.11 0.11" if is_cancelled_swap_class else "0.07 0.12 0.12"
                content.append(_pdf_text(x + 4, y + 8, 8, _shorten(getter(item), max_chars), text_color))
                x += col_width

    content.append(_pdf_text(left, 38, 8, "※ 빨간색 항목은 교체로 원 담당 교사가 해당 시각에 수업하지 않는 수업입니다.", "0.73 0.11 0.11"))
    content.append(_pdf_text(left, 24, 8, "※ 본 문서는 시스템에서 확정된 교체·보강 내역을 기준으로 자동 생성되었습니다."))
    return "".join(content)


def build_plan_pdf(plan: dict) -> bytes:
    rows_per_page = 18
    items = plan["items"] or []
    chunks = [items[index : index + rows_per_page] for index in range(0, len(items), rows_per_page)] or [[]]
    objects: list[str] = []

    def add_object(body: str) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add_object("")
    pages_id = add_object("")
    cid_font_id = add_object(
        "<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HYGoThic-Medium "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Korea1) /Supplement 2 >> /DW 1000 >>"
    )
    font_id = add_object(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /HYGoThic-Medium "
        f"/Encoding /UniKS-UCS2-H /DescendantFonts [{cid_font_id} 0 R] >>"
    )
    page_ids: list[int] = []
    page_count = len(chunks)
    for page_index, chunk in enumerate(chunks, start=1):
        stream = _build_pdf_content(plan, chunk, page_index, page_count)
        content_id = add_object(_pdf_stream_object(stream))
        page_id = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 842 595] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    objects[pages_id - 1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids "
        f"[{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] >>"
    )
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>"

    output = BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n{body}\nendobj\n".encode("ascii"))
    xref_offset = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return output.getvalue()
