# Pricing Export Summary

- Export time: generated from live pages.
- 78 code base models: 118
- 78 code groups found: 12 total, 9 enabled
- 78 code group-model rows: 217
- GeekAI models: 648
- Exact model-id matches (78 -> GeekAI): 58
- 78 models without exact GeekAI id match: 60

## Files

- `78code_models_base.csv`: 78 code base model list.
- `78code_groups.csv`: 78 code group names and multipliers.
- `78code_group_models.csv`: enabled-group membership and effective input/output after multiplier.
- `78code_group_price_items.csv`: enabled-group itemized effective prices for every visible price item.
- `geekai_models.csv`: GeekAI full model list with text-tier columns.
- `geekai_price_items.csv`: GeekAI itemized price lines.
- `comparison_exact_match.csv`: compare 78 base models against GeekAI exact `model_id` matches.

## Notes

- 78 code effective prices are computed as `displayed price x group multiplier`.
- Disabled 78 groups are listed in `78code_groups.csv` but not expanded into membership rows.
- Exact-match comparison uses `model_id` equality only; aliases or family-level matches are not merged.
