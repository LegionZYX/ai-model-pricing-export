from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def total_cost(input_cost: float | None, output_cost: float | None) -> float | None:
    if input_cost is None or output_cost is None:
        return None
    return input_cost + output_cost


def build_recommendations() -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    exact_rows = read_csv(OUT_DIR / "comparison_exact_match.csv")
    group_rows = read_csv(OUT_DIR / "78code_group_models.csv")

    best_78_by_model: dict[str, dict[str, Any]] = {}
    for row in group_rows:
        model_id = row["model_id"]
        effective_input = parse_float(row["effective_input"])
        effective_output = parse_float(row["effective_output"])
        effective_total = total_cost(effective_input, effective_output)
        candidate = {
            "group_name": row["group_name"],
            "group_multiplier": row["group_multiplier"],
            "effective_input": effective_input,
            "effective_output": effective_output,
            "effective_total": effective_total,
            "base_input": parse_float(row["base_input"]),
            "base_output": parse_float(row["base_output"]),
            "raw_price_lines": row["raw_price_lines"],
        }
        current = best_78_by_model.get(model_id)
        if current is None:
            best_78_by_model[model_id] = candidate
            continue
        current_total = current["effective_total"]
        if effective_total is not None and (current_total is None or effective_total < current_total):
            best_78_by_model[model_id] = candidate

    recommendation_rows: list[dict[str, Any]] = []
    no_match_rows: list[dict[str, Any]] = []
    matched_count = 0
    recommend_78 = 0
    recommend_geekai = 0
    recommend_tie = 0

    for row in exact_rows:
        model_id = row["model_id"]
        best_78 = best_78_by_model.get(model_id)
        best_78_input = best_78["effective_input"] if best_78 else None
        best_78_output = best_78["effective_output"] if best_78 else None
        best_78_total = best_78["effective_total"] if best_78 else None

        tiers = [
            ("low", parse_float(row["geekai_low_input"]), parse_float(row["geekai_low_output"])),
            ("balanced", parse_float(row["geekai_balanced_input"]), parse_float(row["geekai_balanced_output"])),
            ("high", parse_float(row["geekai_high_input"]), parse_float(row["geekai_high_output"])),
            ("official", parse_float(row["geekai_official_input"]), parse_float(row["geekai_official_output"])),
        ]

        geek_candidates = []
        for tier_name, input_cost, output_cost in tiers:
            geek_total = total_cost(input_cost, output_cost)
            if geek_total is None:
                continue
            geek_candidates.append(
                {
                    "tier_name": tier_name,
                    "input": input_cost,
                    "output": output_cost,
                    "total": geek_total,
                }
            )

        best_geek = min(geek_candidates, key=lambda item: item["total"]) if geek_candidates else None

        recommendation = "no_exact_match"
        cheaper_by = None
        ratio_78_vs_geekai = None
        comparison_note = ""

        if row["geekai_match"] == "yes" and best_78 and best_geek:
            matched_count += 1
            ratio_78_vs_geekai = best_78_total / best_geek["total"] if best_geek["total"] else None
            cheaper_by = abs(best_78_total - best_geek["total"])

            if abs(best_78_total - best_geek["total"]) < 1e-9:
                recommendation = "tie"
                recommend_tie += 1
            elif best_78_total < best_geek["total"]:
                recommendation = "78"
                recommend_78 += 1
            else:
                recommendation = "GeekAI"
                recommend_geekai += 1

            if best_78_input is not None and best_78_output is not None:
                if best_geek["input"] is not None and best_geek["output"] is not None:
                    if best_78_input < best_geek["input"] and best_78_output < best_geek["output"]:
                        comparison_note = "78 lower on both input and output"
                    elif best_78_input > best_geek["input"] and best_78_output > best_geek["output"]:
                        comparison_note = "GeekAI lower on both input and output"
                    else:
                        comparison_note = "mixed input/output advantage"
        else:
            no_match_rows.append(
                {
                    "model_id": model_id,
                    "model_78_name": row["model_78_name"],
                    "billing_type_78": row["billing_type_78"],
                    "input_78": row["input_78"],
                    "output_78": row["output_78"],
                    "best_78_group": best_78["group_name"] if best_78 else "",
                    "best_78_effective_input": format_float(best_78_input),
                    "best_78_effective_output": format_float(best_78_output),
                    "best_78_effective_total": format_float(best_78_total),
                    "geekai_match": row["geekai_match"],
                }
            )

        recommendation_rows.append(
            {
                "model_id": model_id,
                "model_78_name": row["model_78_name"],
                "billing_type_78": row["billing_type_78"],
                "input_78_global": row["input_78"],
                "output_78_global": row["output_78"],
                "best_78_group": best_78["group_name"] if best_78 else "",
                "best_78_multiplier": best_78["group_multiplier"] if best_78 else "",
                "best_78_effective_input": format_float(best_78_input),
                "best_78_effective_output": format_float(best_78_output),
                "best_78_effective_total": format_float(best_78_total),
                "geekai_match": row["geekai_match"],
                "geekai_display_name": row["geekai_display_name"],
                "geekai_context": row["geekai_context"],
                "geekai_best_tier": best_geek["tier_name"] if best_geek else "",
                "geekai_best_input": format_float(best_geek["input"]) if best_geek else "",
                "geekai_best_output": format_float(best_geek["output"]) if best_geek else "",
                "geekai_best_total": format_float(best_geek["total"]) if best_geek else "",
                "recommended_vendor": recommendation,
                "cheaper_by_total": format_float(cheaper_by),
                "ratio_78_vs_geekai": format_float(ratio_78_vs_geekai),
                "comparison_note": comparison_note,
            }
        )

    summary = "\n".join(
        [
            "# Recommendation Summary",
            "",
            "- Assumption: compare by equal-weight total cost = 1M input + 1M output.",
            f"- 78 models with exact GeekAI match: {matched_count}",
            f"- Recommended to buy from 78: {recommend_78}",
            f"- Recommended to buy from GeekAI: {recommend_geekai}",
            f"- Ties: {recommend_tie}",
            f"- 78 models without exact GeekAI match: {len(no_match_rows)}",
            "",
            "## Files",
            "",
            "- `recommendation_exact_match.csv`: main recommendation table using 78 as primary side.",
            "- `recommendation_no_exact_match.csv`: 78 models that do not have exact GeekAI `model_id` matches.",
        ]
    ) + "\n"

    return recommendation_rows, no_match_rows, summary


def main() -> None:
    recommendation_rows, no_match_rows, summary = build_recommendations()

    write_csv(
        OUT_DIR / "recommendation_exact_match.csv",
        recommendation_rows,
        [
            "model_id",
            "model_78_name",
            "billing_type_78",
            "input_78_global",
            "output_78_global",
            "best_78_group",
            "best_78_multiplier",
            "best_78_effective_input",
            "best_78_effective_output",
            "best_78_effective_total",
            "geekai_match",
            "geekai_display_name",
            "geekai_context",
            "geekai_best_tier",
            "geekai_best_input",
            "geekai_best_output",
            "geekai_best_total",
            "recommended_vendor",
            "cheaper_by_total",
            "ratio_78_vs_geekai",
            "comparison_note",
        ],
    )

    write_csv(
        OUT_DIR / "recommendation_no_exact_match.csv",
        no_match_rows,
        [
            "model_id",
            "model_78_name",
            "billing_type_78",
            "input_78",
            "output_78",
            "best_78_group",
            "best_78_effective_input",
            "best_78_effective_output",
            "best_78_effective_total",
            "geekai_match",
        ],
    )

    (OUT_DIR / "RECOMMENDATION_SUMMARY.md").write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
