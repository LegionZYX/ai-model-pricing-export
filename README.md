# Pricing Compare Export

This repo contains a live export and comparison workflow for:

- `https://www.78code.cc/pricing`
- `https://geekai.co/models`

## What Is Included

- `export_model_pricing.py`: scraper and exporter
- `output/78code_models_base.csv`: full 78 code base model list
- `output/78code_groups.csv`: 78 code group multipliers
- `output/78code_group_models.csv`: group membership plus effective price using group-page displayed prices x multiplier
- `output/78code_group_price_items.csv`: itemized effective prices using group-page displayed prices x multiplier
- `output/78code_group_models_old.csv`: previous logic using global base prices x multiplier
- `output/78code_group_price_items_old.csv`: previous itemized logic using global base prices x multiplier
- `output/geekai_models.csv`: full GeekAI model list
- `output/geekai_price_items.csv`: itemized GeekAI prices
- `output/comparison_exact_match.csv`: exact `model_id` comparison using 78 as the primary side
- `output/SUMMARY.md`: export summary

## Run

```powershell
python .\export_model_pricing.py
```

Outputs are written to `output/`.
