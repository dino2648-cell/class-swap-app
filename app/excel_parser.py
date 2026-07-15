from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.security import build_unique_usernames, clean_teacher_name, normalize_whitespace


MAIN_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}

EXPECTED_SHEET_NAME = "주간시간표"
DAY_LABELS = ["월", "화", "수", "목", "금"]
DAY_PERIOD_LIMITS = {0: 7, 1: 7, 2: 7, 3: 7, 4: 6}
COLUMN_TO_TIME = {
    2: (0, 1),
    3: (0, 2),
    4: (0, 3),
    5: (0, 4),
    6: (0, 5),
    7: (0, 6),
    8: (0, 7),
    9: (1, 1),
    10: (1, 2),
    11: (1, 3),
    12: (1, 4),
    13: (1, 5),
    14: (1, 6),
    15: (1, 7),
    16: (2, 1),
    17: (2, 2),
    18: (2, 3),
    19: (2, 4),
    20: (2, 5),
    21: (2, 6),
    22: (2, 7),
    23: (3, 1),
    24: (3, 2),
    25: (3, 3),
    26: (3, 4),
    27: (3, 5),
    28: (3, 6),
    29: (3, 7),
    30: (4, 1),
    31: (4, 2),
    32: (4, 3),
    33: (4, 4),
    34: (4, 5),
    35: (4, 6),
}

TRAVEL_RE = re.compile(r"^(?P<school>.+?)\((?P<hours>\d+)시간\)$")
CLASS_RE = re.compile(r"^(?P<class_code>중[123]|[123]\d{2})\s+(?P<subject>.+)$")


class TimetableValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class TeacherRow:
    row_index: int
    raw_name: str
    display_name: str
    suggested_username: str


def _normalize_target(target: str) -> str:
    if target.startswith("/"):
        target = target[1:]
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _column_name(column_index: int) -> str:
    result = ""
    current = column_index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _parse_ref(cell_ref: str) -> tuple[int, int]:
    letters = "".join(char for char in cell_ref if char.isalpha())
    digits = "".join(char for char in cell_ref if char.isdigit())
    column_index = 0
    for char in letters:
        column_index = column_index * 26 + ord(char.upper()) - 64
    return int(digits), column_index


def _iter_range(start_ref: str, end_ref: str) -> list[str]:
    start_row, start_col = _parse_ref(start_ref)
    end_row, end_col = _parse_ref(end_ref)
    refs: list[str] = []
    for row_index in range(start_row, end_row + 1):
        for column_index in range(start_col, end_col + 1):
            refs.append(f"{_column_name(column_index)}{row_index}")
    return refs


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for item in shared_root.findall("a:si", MAIN_NS):
        text = "".join(node.text or "" for node in item.iterfind(".//a:t", MAIN_NS))
        shared_strings.append(text)
    return shared_strings


def _read_sheet_cells(archive: ZipFile, target: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    root = ET.fromstring(archive.read(target))
    shared_strings = _read_shared_strings(archive)
    cells: dict[str, str] = {}
    merged_masters: dict[str, str] = {}
    merged_ranges: list[str] = []

    for cell in root.findall(".//a:sheetData/a:row/a:c", MAIN_NS):
        ref = cell.attrib["r"]
        cell_type = cell.attrib.get("t")
        value: str | None = None
        if cell_type == "inlineStr":
            value = "".join(node.text or "" for node in cell.findall(".//a:t", MAIN_NS))
        else:
            value_node = cell.find("a:v", MAIN_NS)
            if value_node is not None:
                value = value_node.text or ""
                if cell_type == "s":
                    value = shared_strings[int(value)]
        if value is not None:
            cells[ref] = value

    for merged in root.findall("a:mergeCells/a:mergeCell", MAIN_NS):
        merged_ref = merged.attrib["ref"]
        merged_ranges.append(merged_ref)
        start_ref, end_ref = merged_ref.split(":")
        for ref in _iter_range(start_ref, end_ref):
            merged_masters[ref] = start_ref

    return cells, merged_masters, merged_ranges


def _get_display_value(cells: dict[str, str], merged_masters: dict[str, str], ref: str) -> str:
    direct = cells.get(ref)
    if direct is not None:
        return direct
    master = merged_masters.get(ref)
    if master:
        return cells.get(master, "")
    return ""


def _validate_headers(cells: dict[str, str], merged_masters: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if normalize_whitespace(_get_display_value(cells, merged_masters, "A2")) != "교사":
        errors.append("주간시간표 시트의 A2 셀은 '교사'여야 합니다.")

    expected_days = {"B2": "월", "I2": "화", "P2": "수", "W2": "목", "AD2": "금"}
    for ref, expected in expected_days.items():
        actual = normalize_whitespace(_get_display_value(cells, merged_masters, ref))
        if actual != expected:
            errors.append(f"주간시간표 시트의 {ref} 셀은 '{expected}'여야 합니다.")

    for column_index, (weekday, period) in COLUMN_TO_TIME.items():
        ref = f"{_column_name(column_index)}3"
        actual = normalize_whitespace(_get_display_value(cells, merged_masters, ref))
        if actual != str(period):
            errors.append(f"주간시간표 시트의 {ref} 셀은 '{period}'여야 합니다.")

    return errors


def _parse_schedule_text(
    value: str,
    teacher: TeacherRow,
    day_index: int,
    period: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = normalize_whitespace(value)
    failures: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []

    travel_match = TRAVEL_RE.fullmatch(normalized)
    if travel_match:
        duration = int(travel_match.group("hours"))
        if period + duration - 1 > DAY_PERIOD_LIMITS[day_index]:
            failures.append(
                {
                    "teacher_name": teacher.display_name,
                    "row_index": teacher.row_index,
                    "weekday": day_index,
                    "day_label": DAY_LABELS[day_index],
                    "period": period,
                    "value": normalized,
                    "reason": "순회 수업 시간이 해당 요일의 마지막 교시를 초과합니다.",
                }
            )
            return [], failures
        for offset in range(duration):
            slots.append(
                {
                    "teacher_row_index": teacher.row_index,
                    "teacher_schedule_label": teacher.raw_name,
                    "teacher_display_name": teacher.display_name,
                    "teacher_username": teacher.suggested_username,
                    "weekday": day_index,
                    "day_label": DAY_LABELS[day_index],
                    "period": period + offset,
                    "slot_type": "travel",
                    "class_code": None,
                    "subject": None,
                    "location_label": normalize_whitespace(travel_match.group("school")),
                    "duration": duration,
                    "source_text": normalized,
                }
            )
        return slots, failures

    class_match = CLASS_RE.fullmatch(normalized)
    if class_match:
        slots.append(
            {
                "teacher_row_index": teacher.row_index,
                "teacher_schedule_label": teacher.raw_name,
                "teacher_display_name": teacher.display_name,
                "teacher_username": teacher.suggested_username,
                "weekday": day_index,
                "day_label": DAY_LABELS[day_index],
                "period": period,
                "slot_type": "class",
                "class_code": class_match.group("class_code"),
                "subject": normalize_whitespace(class_match.group("subject")),
                "location_label": None,
                "duration": 1,
                "source_text": normalized,
            }
        )
        return slots, failures

    failures.append(
        {
            "teacher_name": teacher.display_name,
            "row_index": teacher.row_index,
            "weekday": day_index,
            "day_label": DAY_LABELS[day_index],
            "period": period,
            "value": normalized,
            "reason": "학반+과목 또는 학교명(N시간) 형식을 인식하지 못했습니다.",
        }
    )
    return [], failures


def parse_timetable_workbook(file_bytes: bytes, filename: str) -> dict[str, Any]:
    with ZipFile(BytesIO(file_bytes)) as archive:
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        workbook_rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: _normalize_target(rel.attrib["Target"])
            for rel in workbook_rels.findall("rel:Relationship", REL_NS)
        }
        sheet_targets = {
            sheet.attrib["name"]: rel_map[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            for sheet in workbook_root.findall("a:sheets/a:sheet", MAIN_NS)
        }

        if EXPECTED_SHEET_NAME not in sheet_targets:
            raise TimetableValidationError(
                [f"표준 양식과 다릅니다. '{EXPECTED_SHEET_NAME}' 시트를 찾지 못했습니다."]
            )

        cells, merged_masters, merged_ranges = _read_sheet_cells(archive, sheet_targets[EXPECTED_SHEET_NAME])

    header_errors = _validate_headers(cells, merged_masters)
    if header_errors:
        raise TimetableValidationError(header_errors)

    all_rows = {_parse_ref(ref)[0] for ref in cells.keys()}
    if merged_ranges:
        for merged_ref in merged_ranges:
            start_ref, end_ref = merged_ref.split(":")
            start_row, _ = _parse_ref(start_ref)
            end_row, _ = _parse_ref(end_ref)
            for row_index in range(start_row, end_row + 1):
                all_rows.add(row_index)
    max_row = max(all_rows or {3})

    warnings: list[str] = []
    ignored_rows: list[str] = []
    teacher_rows: list[tuple[int, str, str]] = []

    for row_index in range(4, max_row + 1):
        teacher_ref = f"A{row_index}"
        raw_name = normalize_whitespace(_get_display_value(cells, merged_masters, teacher_ref))
        row_values = [
            normalize_whitespace(_get_display_value(cells, merged_masters, f"{_column_name(col)}{row_index}"))
            for col in range(2, 36)
        ]
        row_has_schedule = any(value for value in row_values)
        if not raw_name and not row_has_schedule:
            continue
        if raw_name == "홍길동":
            ignored_rows.append(f"{row_index}행의 예시 교사 '홍길동'은 경고 후 제외했습니다.")
            continue
        if not raw_name and row_has_schedule:
            warnings.append(f"{row_index}행은 교사 이름이 비어 있어 제외했습니다.")
            continue
        teacher_rows.append((row_index, raw_name, clean_teacher_name(raw_name)))

    display_names = [display_name for _, _, display_name in teacher_rows]
    usernames = build_unique_usernames(display_names)
    teachers = [
        TeacherRow(
            row_index=row_index,
            raw_name=raw_name,
            display_name=display_name,
            suggested_username=usernames[index],
        )
        for index, (row_index, raw_name, display_name) in enumerate(teacher_rows)
    ]

    occupied: dict[tuple[int, int, int], dict[str, Any]] = {}
    slots: list[dict[str, Any]] = []
    failed_cells: list[dict[str, Any]] = []

    for teacher in teachers:
        skip_until: dict[int, int] = {}
        processed_merged_refs: set[str] = set()
        for column_index, (day_index, period) in COLUMN_TO_TIME.items():
            if skip_until.get(day_index, 0) >= period:
                continue
            ref = f"{_column_name(column_index)}{teacher.row_index}"
            master_ref = merged_masters.get(ref, ref)
            if master_ref in processed_merged_refs:
                continue
            raw_value = _get_display_value(cells, merged_masters, ref)
            normalized = normalize_whitespace(raw_value)
            if not normalized:
                continue
            parsed_slots, parse_failures = _parse_schedule_text(normalized, teacher, day_index, period)
            if ref in merged_masters:
                processed_merged_refs.add(master_ref)
            for failure in parse_failures:
                failure["cell_ref"] = ref
                failed_cells.append(failure)
            if parse_failures:
                continue
            for slot in parsed_slots:
                key = (teacher.row_index, slot["weekday"], slot["period"])
                if key in occupied:
                    failed_cells.append(
                        {
                            "cell_ref": ref,
                            "teacher_name": teacher.display_name,
                            "row_index": teacher.row_index,
                            "weekday": day_index,
                            "day_label": DAY_LABELS[day_index],
                            "period": period,
                            "value": normalized,
                            "reason": "이미 다른 수업 또는 순회로 점유된 교시와 겹칩니다.",
                        }
                    )
                    parsed_slots = []
                    break
                occupied[key] = slot
            if parsed_slots:
                slots.extend(parsed_slots)
                if parsed_slots[0]["slot_type"] == "travel":
                    skip_until[day_index] = parsed_slots[-1]["period"]

    out_of_range_values = []
    for ref, value in cells.items():
        row_index, column_index = _parse_ref(ref)
        if column_index <= 35:
            continue
        normalized = normalize_whitespace(value)
        if normalized:
            out_of_range_values.append({"cell_ref": ref, "value": normalized, "row_index": row_index})
    if out_of_range_values:
        refs = ", ".join(item["cell_ref"] for item in out_of_range_values[:10])
        warnings.append(f"35열 범위를 벗어난 데이터 {len(out_of_range_values)}건은 무시했습니다. 예: {refs}")

    warnings.extend(ignored_rows)

    preview = {
        "uploaded_filename": filename,
        "teachers": [
            {
                "row_index": teacher.row_index,
                "raw_name": teacher.raw_name,
                "display_name": teacher.display_name,
                "suggested_username": teacher.suggested_username,
            }
            for teacher in teachers
        ],
        "slots": slots,
        "failed_cells": failed_cells,
        "warnings": warnings,
        "summary": {
            "teacher_count": len(teachers),
            "class_slot_count": sum(1 for slot in slots if slot["slot_type"] == "class"),
            "travel_slot_count": sum(1 for slot in slots if slot["slot_type"] == "travel"),
            "failed_cell_count": len(failed_cells),
            "warning_count": len(warnings),
        },
    }
    return preview


def apply_preview_corrections(preview: dict[str, Any], corrections: list[dict[str, str]]) -> dict[str, Any]:
    if not corrections:
        return preview

    teachers_by_row = {
        item["row_index"]: TeacherRow(
            row_index=item["row_index"],
            raw_name=item["raw_name"],
            display_name=item["display_name"],
            suggested_username=item["suggested_username"],
        )
        for item in preview["teachers"]
    }
    corrected_preview = {
        "uploaded_filename": preview["uploaded_filename"],
        "teachers": list(preview["teachers"]),
        "slots": [dict(slot) for slot in preview["slots"]],
        "failed_cells": [dict(cell) for cell in preview["failed_cells"]],
        "warnings": list(preview["warnings"]),
        "summary": dict(preview["summary"]),
    }

    correction_map = {item["cell_ref"]: item.get("value", "") for item in corrections}
    failed_by_ref = {item["cell_ref"]: dict(item) for item in corrected_preview["failed_cells"]}
    occupied = {
        (slot["teacher_row_index"], slot["weekday"], slot["period"]): slot for slot in corrected_preview["slots"]
    }
    remaining: list[dict[str, Any]] = []

    for failed in corrected_preview["failed_cells"]:
        ref = failed["cell_ref"]
        if ref not in correction_map:
            remaining.append(failed)
            continue
        override = normalize_whitespace(correction_map[ref])
        row_index = failed["row_index"]
        teacher = teachers_by_row[row_index]
        if not override:
            corrected_preview["warnings"].append(f"{ref} 셀은 빈값으로 확정되어 제외했습니다.")
            continue

        parsed_slots, parse_failures = _parse_schedule_text(
            override,
            teacher,
            failed["weekday"],
            failed["period"],
        )
        if parse_failures:
            for parse_failure in parse_failures:
                parse_failure["cell_ref"] = ref
                remaining.append(parse_failure)
            continue

        conflict = False
        for slot in parsed_slots:
            key = (slot["teacher_row_index"], slot["weekday"], slot["period"])
            if key in occupied:
                remaining.append(
                    {
                        "cell_ref": ref,
                        "teacher_name": teacher.display_name,
                        "row_index": teacher.row_index,
                        "weekday": failed["weekday"],
                        "day_label": failed["day_label"],
                        "period": failed["period"],
                        "value": override,
                        "reason": "수동 수정값이 기존 수업 또는 순회와 겹칩니다.",
                    }
                )
                conflict = True
                break
        if conflict:
            continue
        for slot in parsed_slots:
            occupied[(slot["teacher_row_index"], slot["weekday"], slot["period"])] = slot
            corrected_preview["slots"].append(slot)

    corrected_preview["failed_cells"] = remaining
    corrected_preview["summary"] = {
        "teacher_count": len(corrected_preview["teachers"]),
        "class_slot_count": sum(1 for slot in corrected_preview["slots"] if slot["slot_type"] == "class"),
        "travel_slot_count": sum(1 for slot in corrected_preview["slots"] if slot["slot_type"] == "travel"),
        "failed_cell_count": len(corrected_preview["failed_cells"]),
        "warning_count": len(corrected_preview["warnings"]),
    }
    return corrected_preview
