import json
from pathlib import Path

from nankan_predictor.storage.repository import Repository
from nankan_predictor.features.builder import FeatureBuilder


def update_meta(model_name: str, target: str, from_date: str, to_date: str):
    repo = Repository()
    builder = FeatureBuilder(repo)
    X, y = builder.build_training_set(from_date, to_date, target=target)
    features = list(X.columns)

    meta_path = Path("data/models") / f"{model_name}_{target}_meta.json"
    if not meta_path.exists():
        meta_path = Path("data/models") / f"{model_name}_{target}_meta.json"

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    meta["features"] = features
    meta["updated_at"] = __import__("datetime").datetime.now().isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Updated meta: {meta_path} (features={len(features)})")


def main():
    from_date = "2023-01-01"
    to_date = "2026-02-12"
    model_base = "nankan_v1"

    update_meta(model_base, "win", from_date, to_date)
    update_meta(model_base, "place", from_date, to_date)


if __name__ == '__main__':
    main()
