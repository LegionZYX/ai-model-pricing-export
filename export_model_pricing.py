from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"

PRICE_RE = re.compile(
    r"^[￥¥](?P<first>\d+(?:\.\d+)?)(?:~(?P<second>\d+(?:\.\d+)?))?/(?P<unit>\S+)(?:\s+(?P<label>.+))?$"
)
FREE_RE = re.compile(r"^免费(?:\s+(?P<label>.+))?$")
MULTIPLIER_RE = re.compile(r"x(?P<value>\d+(?:\.\d+)?)")


@dataclass
class GroupInfo:
    name: str
    multiplier: float | None
    multiplier_raw: str
    disabled: bool
    button_index: int


def ensure_output_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def scrape_78_with_retries(browser: Browser, attempts: int = 3) -> tuple[list[dict[str, Any]], list[GroupInfo], list[dict[str, Any]]]:
    last_result: tuple[list[dict[str, Any]], list[GroupInfo], list[dict[str, Any]]] = ([], [], [])
    for _ in range(attempts):
        last_result = scrape_78(browser)
        models, groups, _group_models = last_result
        if models and groups:
            return last_result
    return last_result


def normalize_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def parse_price_line(raw_line: str) -> dict[str, Any]:
    match = PRICE_RE.match(raw_line)
    if match:
        first = parse_numeric(match.group("first"))
        second = parse_numeric(match.group("second"))
        return {
            "raw_line": raw_line,
            "charge_type": "paid",
            "amount_1": first,
            "amount_2": second,
            "unit": match.group("unit"),
            "label": match.group("label") or "",
        }

    free_match = FREE_RE.match(raw_line)
    if free_match:
        return {
            "raw_line": raw_line,
            "charge_type": "free",
            "amount_1": 0.0,
            "amount_2": None,
            "unit": "",
            "label": free_match.group("label") or "",
        }

    return {
        "raw_line": raw_line,
        "charge_type": "unknown",
        "amount_1": None,
        "amount_2": None,
        "unit": "",
        "label": "",
    }


def multiply_amount(amount: float | None, multiplier: float | None) -> float | None:
    if amount is None or multiplier is None:
        return amount
    return round(amount * multiplier, 6)


def format_amount(amount: float | None) -> str:
    if amount is None:
        return ""
    return f"{amount:.6f}".rstrip("0").rstrip(".")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def scrape_78_groups(page: Page) -> list[GroupInfo]:
    buttons = page.locator(".sbg-button")
    groups: list[GroupInfo] = []

    for index in range(buttons.count()):
        button = buttons.nth(index)
        text = " | ".join(normalize_lines(button.inner_text()))
        if "全部分组" in text:
            groups.append(
                GroupInfo(
                    name="全部",
                    multiplier=None,
                    multiplier_raw="",
                    disabled=False,
                    button_index=index,
                )
            )
            continue

        multiplier_match = MULTIPLIER_RE.search(text)
        if not multiplier_match:
            continue

        lines = normalize_lines(button.inner_text())
        groups.append(
            GroupInfo(
                name=lines[0],
                multiplier=float(multiplier_match.group("value")),
                multiplier_raw=multiplier_match.group(0),
                disabled=button.is_disabled(),
                button_index=index,
            )
        )

    return groups


def parse_78_card(card_text: str) -> dict[str, Any] | None:
    lines = normalize_lines(card_text)
    if not lines or lines[0].startswith("全部供应商"):
        return None

    display_name = lines[0]
    model_id = lines[0]
    cursor = 1
    if len(lines) > 1:
        second_line = lines[1]
        if (
            not second_line.startswith(("输入", "输出", "￥", "¥", "免费"))
            and second_line not in {"按量计费", "按次计费"}
        ):
            model_id = second_line
            cursor = 2

    price_lines = []
    billing_type = ""

    for line in lines[cursor:]:
        if line in {"按量计费", "按次计费"}:
            billing_type = line
            break
        price_lines.append(line)

    parsed_items = []
    pending_kind = None
    for line in price_lines:
        if line in {"输入", "输出"}:
            pending_kind = line
            continue

        price_match = re.match(r"^(输入|输出)\s+[￥¥](?P<amount>\d+(?:\.\d+)?)/(?P<unit>\S+)$", line)
        if price_match:
            kind = price_match.group(1)
            parsed_items.append(
                {
                    "kind": kind,
                    "charge_type": "paid",
                    "amount_1": float(price_match.group("amount")),
                    "amount_2": None,
                    "unit": price_match.group("unit"),
                    "label": "",
                    "raw_line": line,
                }
            )
            pending_kind = None
            continue

        if line.startswith("￥") and pending_kind:
            parsed = parse_price_line(line)
            parsed["kind"] = pending_kind
            parsed_items.append(parsed)
            pending_kind = None
            continue

        parsed = parse_price_line(line)
        parsed["kind"] = pending_kind or ""
        parsed_items.append(parsed)
        pending_kind = None

    input_item = next((item for item in parsed_items if item["kind"] == "输入"), None)
    output_item = next((item for item in parsed_items if item["kind"] == "输出"), None)

    return {
        "model_id": model_id,
        "display_name": display_name,
        "billing_type": billing_type,
        "raw_lines": price_lines,
        "price_items": parsed_items,
        "base_input": input_item["amount_1"] if input_item else None,
        "base_output": output_item["amount_1"] if output_item else None,
    }


def get_78_total_pages(page: Page) -> int:
    items = page.locator("li.semi-page-item")
    pages = []
    for index in range(items.count()):
        text = items.nth(index).inner_text().strip()
        if text.isdigit():
            pages.append(int(text))
    return max(pages) if pages else 1


def scrape_78_cards_on_current_page(page: Page) -> list[dict[str, Any]]:
    texts = page.locator(".semi-card").evaluate_all(
        "(nodes) => nodes.map((node) => node.innerText || '')"
    )
    models: list[dict[str, Any]] = []
    for text in texts:
        parsed = parse_78_card(text)
        if parsed:
            models.append(parsed)
    return models


def click_78_page(page: Page, page_number: int) -> None:
    locator = page.locator(f'li.semi-page-item[aria-label="Page {page_number}"]')
    locator.click()
    page.wait_for_timeout(800)
    page.wait_for_load_state("networkidle")


def scrape_78_group_models(browser: Browser, group: GroupInfo) -> list[dict[str, Any]]:
    page = browser.new_page(viewport={"width": 1440, "height": 1800})
    page.goto("https://www.78code.cc/pricing", wait_until="networkidle", timeout=120000)

    button = page.locator(".sbg-button").nth(group.button_index)
    if not group.disabled:
        button.click()
        page.wait_for_timeout(800)
        page.wait_for_load_state("networkidle")

    total_pages = get_78_total_pages(page)
    collected: dict[str, dict[str, Any]] = {}

    for page_number in range(1, total_pages + 1):
        if page_number > 1:
            click_78_page(page, page_number)

        for model in scrape_78_cards_on_current_page(page):
            model["group_name"] = group.name
            model["group_multiplier"] = group.multiplier
            model["group_multiplier_raw"] = group.multiplier_raw
            model["group_disabled"] = group.disabled
            model["page_number"] = page_number
            collected[model["model_id"]] = model

    page.close()
    return list(collected.values())


def scrape_78(browser: Browser) -> tuple[list[dict[str, Any]], list[GroupInfo], list[dict[str, Any]]]:
    page = browser.new_page(viewport={"width": 1440, "height": 1800})
    page.goto("https://www.78code.cc/pricing", wait_until="networkidle", timeout=120000)

    groups = scrape_78_groups(page)
    total_pages = get_78_total_pages(page)

    base_models: dict[str, dict[str, Any]] = {}
    for page_number in range(1, total_pages + 1):
        if page_number > 1:
            click_78_page(page, page_number)
        for model in scrape_78_cards_on_current_page(page):
            model["page_number"] = page_number
            base_models[model["model_id"]] = model

    page.close()

    group_models: list[dict[str, Any]] = []
    for group in groups:
        if group.name == "全部" or group.disabled:
            continue
        group_models.extend(scrape_78_group_models(browser, group))

    return list(base_models.values()), groups, group_models


def parse_geekai_row(row_text: str) -> dict[str, Any] | None:
    lines = normalize_lines(row_text)
    if len(lines) < 4 or lines[0] == "模型名称":
        return None

    display_name = lines[0]
    model_id = lines[1]
    context = lines[-2]
    price_lines = lines[2:-2]
    price_items = [parse_price_line(line) for line in price_lines]

    return {
        "display_name": display_name,
        "model_id": model_id,
        "context": context,
        "raw_lines": price_lines,
        "price_items": price_items,
    }


def scrape_geekai(browser: Browser) -> list[dict[str, Any]]:
    page = browser.new_page(viewport={"width": 1440, "height": 2000})
    page.goto("https://geekai.co/models", wait_until="networkidle", timeout=120000)

    rows = page.locator("tr")
    models: list[dict[str, Any]] = []
    for index in range(1, rows.count()):
        parsed = parse_geekai_row(rows.nth(index).inner_text())
        if parsed:
            models.append(parsed)

    page.close()
    return models


def extract_geekai_text_tiers(price_items: list[dict[str, Any]]) -> dict[str, float | None]:
    result = {
        "low_input": None,
        "low_output": None,
        "balanced_input": None,
        "balanced_output": None,
        "high_input": None,
        "high_output": None,
        "official_input": None,
        "official_output": None,
    }

    for item in price_items:
        if item["charge_type"] != "paid":
            continue
        if item["amount_2"] is None:
            continue

        label = item["label"]
        if "低价" in label:
            result["low_input"] = item["amount_1"]
            result["low_output"] = item["amount_2"]
        elif "均衡" in label:
            result["balanced_input"] = item["amount_1"]
            result["balanced_output"] = item["amount_2"]
        elif "高可用" in label:
            result["high_input"] = item["amount_1"]
            result["high_output"] = item["amount_2"]
        elif "官方价" in label:
            result["official_input"] = item["amount_1"]
            result["official_output"] = item["amount_2"]

    return result


def build_rows_78_base(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for model in sorted(models, key=lambda item: item["model_id"]):
        rows.append(
            {
                "model_id": model["model_id"],
                "display_name": model["display_name"],
                "billing_type": model["billing_type"],
                "base_input": format_amount(model["base_input"]),
                "base_output": format_amount(model["base_output"]),
                "raw_price_lines": " || ".join(model["raw_lines"]),
                "page_number": model["page_number"],
            }
        )
    return rows


def build_rows_78_groups(groups: list[GroupInfo]) -> list[dict[str, Any]]:
    rows = []
    for group in groups:
        rows.append(
            {
                "group_name": group.name,
                "multiplier": "" if group.multiplier is None else format_amount(group.multiplier),
                "multiplier_raw": group.multiplier_raw,
                "disabled": group.disabled,
                "button_index": group.button_index,
            }
        )
    return rows


def build_rows_78_group_models(
    group_models: list[dict[str, Any]],
    base_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_by_id = {model["model_id"]: model for model in base_models}
    rows = []
    for model in sorted(group_models, key=lambda item: (item["group_name"], item["model_id"])):
        base_model = base_by_id.get(model["model_id"], model)
        rows.append(
            {
                "group_name": model["group_name"],
                "group_multiplier": format_amount(model["group_multiplier"]),
                "group_multiplier_raw": model["group_multiplier_raw"],
                "group_disabled": model["group_disabled"],
                "model_id": base_model["model_id"],
                "display_name": base_model["display_name"],
                "billing_type": base_model["billing_type"],
                "base_input": format_amount(base_model["base_input"]),
                "base_output": format_amount(base_model["base_output"]),
                "effective_input": format_amount(multiply_amount(base_model["base_input"], model["group_multiplier"])),
                "effective_output": format_amount(multiply_amount(base_model["base_output"], model["group_multiplier"])),
                "raw_price_lines": " || ".join(base_model["raw_lines"]),
                "page_number": model["page_number"],
            }
        )
    return rows


def build_rows_78_group_price_items(
    group_models: list[dict[str, Any]],
    base_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_by_id = {model["model_id"]: model for model in base_models}
    rows = []
    for model in sorted(group_models, key=lambda item: (item["group_name"], item["model_id"])):
        base_model = base_by_id.get(model["model_id"], model)
        for item in base_model["price_items"]:
            rows.append(
                {
                    "group_name": model["group_name"],
                    "group_multiplier": format_amount(model["group_multiplier"]),
                    "group_disabled": model["group_disabled"],
                    "model_id": base_model["model_id"],
                    "price_kind": item.get("kind", ""),
                    "charge_type": item["charge_type"],
                    "unit": item["unit"],
                    "label": item["label"],
                    "raw_line": item["raw_line"],
                    "base_amount_1": format_amount(item["amount_1"]),
                    "base_amount_2": format_amount(item["amount_2"]),
                    "effective_amount_1": format_amount(multiply_amount(item["amount_1"], model["group_multiplier"])),
                    "effective_amount_2": format_amount(multiply_amount(item["amount_2"], model["group_multiplier"])),
                }
            )
    return rows


def build_rows_geekai(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for model in sorted(models, key=lambda item: item["model_id"]):
        tiers = extract_geekai_text_tiers(model["price_items"])
        rows.append(
            {
                "model_id": model["model_id"],
                "display_name": model["display_name"],
                "context": model["context"],
                "low_input": format_amount(tiers["low_input"]),
                "low_output": format_amount(tiers["low_output"]),
                "balanced_input": format_amount(tiers["balanced_input"]),
                "balanced_output": format_amount(tiers["balanced_output"]),
                "high_input": format_amount(tiers["high_input"]),
                "high_output": format_amount(tiers["high_output"]),
                "official_input": format_amount(tiers["official_input"]),
                "official_output": format_amount(tiers["official_output"]),
                "raw_price_lines": " || ".join(model["raw_lines"]),
            }
        )
    return rows


def build_rows_geekai_price_items(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for model in sorted(models, key=lambda item: item["model_id"]):
        for item in model["price_items"]:
            rows.append(
                {
                    "model_id": model["model_id"],
                    "display_name": model["display_name"],
                    "context": model["context"],
                    "charge_type": item["charge_type"],
                    "unit": item["unit"],
                    "label": item["label"],
                    "raw_line": item["raw_line"],
                    "amount_1": format_amount(item["amount_1"]),
                    "amount_2": format_amount(item["amount_2"]),
                }
            )
    return rows


def build_comparison_rows(
    models_78: list[dict[str, Any]],
    geekai_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    geekai_by_id = {model["model_id"]: model for model in geekai_models}
    rows = []

    for model in sorted(models_78, key=lambda item: item["model_id"]):
        geek_match = geekai_by_id.get(model["model_id"])
        geek_tiers = extract_geekai_text_tiers(geek_match["price_items"]) if geek_match else {}
        rows.append(
            {
                "model_id": model["model_id"],
                "model_78_name": model["display_name"],
                "billing_type_78": model["billing_type"],
                "input_78": format_amount(model["base_input"]),
                "output_78": format_amount(model["base_output"]),
                "geekai_match": "yes" if geek_match else "no",
                "geekai_display_name": geek_match["display_name"] if geek_match else "",
                "geekai_context": geek_match["context"] if geek_match else "",
                "geekai_low_input": format_amount(geek_tiers.get("low_input")),
                "geekai_low_output": format_amount(geek_tiers.get("low_output")),
                "geekai_balanced_input": format_amount(geek_tiers.get("balanced_input")),
                "geekai_balanced_output": format_amount(geek_tiers.get("balanced_output")),
                "geekai_high_input": format_amount(geek_tiers.get("high_input")),
                "geekai_high_output": format_amount(geek_tiers.get("high_output")),
                "geekai_official_input": format_amount(geek_tiers.get("official_input")),
                "geekai_official_output": format_amount(geek_tiers.get("official_output")),
                "geekai_raw_price_lines": " || ".join(geek_match["raw_lines"]) if geek_match else "",
            }
        )

    return rows


def build_summary_markdown(
    models_78: list[dict[str, Any]],
    groups: list[GroupInfo],
    group_models: list[dict[str, Any]],
    geekai_models: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
) -> str:
    enabled_groups = [group for group in groups if not group.disabled and group.name != "全部"]
    exact_matches = [row for row in comparison_rows if row["geekai_match"] == "yes"]
    missing_matches = [row for row in comparison_rows if row["geekai_match"] == "no"]

    lines = [
        "# Pricing Export Summary",
        "",
        f"- Export time: generated from live pages.",
        f"- 78 code base models: {len(models_78)}",
        f"- 78 code groups found: {len(groups)} total, {len(enabled_groups)} enabled",
        f"- 78 code group-model rows: {len(group_models)}",
        f"- GeekAI models: {len(geekai_models)}",
        f"- Exact model-id matches (78 -> GeekAI): {len(exact_matches)}",
        f"- 78 models without exact GeekAI id match: {len(missing_matches)}",
        "",
        "## Files",
        "",
        "- `78code_models_base.csv`: 78 code base model list.",
        "- `78code_groups.csv`: 78 code group names and multipliers.",
        "- `78code_group_models.csv`: enabled-group membership and effective input/output after multiplier.",
        "- `78code_group_price_items.csv`: enabled-group itemized effective prices for every visible price item.",
        "- `geekai_models.csv`: GeekAI full model list with text-tier columns.",
        "- `geekai_price_items.csv`: GeekAI itemized price lines.",
        "- `comparison_exact_match.csv`: compare 78 base models against GeekAI exact `model_id` matches.",
        "",
        "## Notes",
        "",
        "- 78 code effective prices are computed as `displayed price x group multiplier`.",
        "- Disabled 78 groups are listed in `78code_groups.csv` but not expanded into membership rows.",
        "- Exact-match comparison uses `model_id` equality only; aliases or family-level matches are not merged.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_output_dir()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        models_78, groups_78, group_models_78 = scrape_78_with_retries(browser)
        geekai_models = scrape_geekai(browser)

        browser.close()

    comparison_rows = build_comparison_rows(models_78, geekai_models)

    rows_78_base = build_rows_78_base(models_78)
    rows_78_groups = build_rows_78_groups(groups_78)
    rows_78_group_models = build_rows_78_group_models(group_models_78, models_78)
    rows_78_group_items = build_rows_78_group_price_items(group_models_78, models_78)
    rows_geekai = build_rows_geekai(geekai_models)
    rows_geekai_items = build_rows_geekai_price_items(geekai_models)

    write_csv(
        OUT_DIR / "78code_models_base.csv",
        rows_78_base,
        [
            "model_id",
            "display_name",
            "billing_type",
            "base_input",
            "base_output",
            "raw_price_lines",
            "page_number",
        ],
    )
    write_csv(
        OUT_DIR / "78code_groups.csv",
        rows_78_groups,
        ["group_name", "multiplier", "multiplier_raw", "disabled", "button_index"],
    )
    write_csv(
        OUT_DIR / "78code_group_models.csv",
        rows_78_group_models,
        [
            "group_name",
            "group_multiplier",
            "group_multiplier_raw",
            "group_disabled",
            "model_id",
            "display_name",
            "billing_type",
            "base_input",
            "base_output",
            "effective_input",
            "effective_output",
            "raw_price_lines",
            "page_number",
        ],
    )
    write_csv(
        OUT_DIR / "78code_group_price_items.csv",
        rows_78_group_items,
        [
            "group_name",
            "group_multiplier",
            "group_disabled",
            "model_id",
            "price_kind",
            "charge_type",
            "unit",
            "label",
            "raw_line",
            "base_amount_1",
            "base_amount_2",
            "effective_amount_1",
            "effective_amount_2",
        ],
    )
    write_csv(
        OUT_DIR / "geekai_models.csv",
        rows_geekai,
        [
            "model_id",
            "display_name",
            "context",
            "low_input",
            "low_output",
            "balanced_input",
            "balanced_output",
            "high_input",
            "high_output",
            "official_input",
            "official_output",
            "raw_price_lines",
        ],
    )
    write_csv(
        OUT_DIR / "geekai_price_items.csv",
        rows_geekai_items,
        [
            "model_id",
            "display_name",
            "context",
            "charge_type",
            "unit",
            "label",
            "raw_line",
            "amount_1",
            "amount_2",
        ],
    )
    write_csv(
        OUT_DIR / "comparison_exact_match.csv",
        comparison_rows,
        [
            "model_id",
            "model_78_name",
            "billing_type_78",
            "input_78",
            "output_78",
            "geekai_match",
            "geekai_display_name",
            "geekai_context",
            "geekai_low_input",
            "geekai_low_output",
            "geekai_balanced_input",
            "geekai_balanced_output",
            "geekai_high_input",
            "geekai_high_output",
            "geekai_official_input",
            "geekai_official_output",
            "geekai_raw_price_lines",
        ],
    )

    save_json(OUT_DIR / "78code_models_base.json", rows_78_base)
    save_json(OUT_DIR / "78code_groups.json", rows_78_groups)
    save_json(OUT_DIR / "78code_group_models.json", rows_78_group_models)
    save_json(OUT_DIR / "geekai_models.json", rows_geekai)
    save_json(OUT_DIR / "comparison_exact_match.json", comparison_rows)

    (OUT_DIR / "SUMMARY.md").write_text(
        build_summary_markdown(models_78, groups_78, group_models_78, geekai_models, comparison_rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
