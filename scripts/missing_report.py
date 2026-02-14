from nankan_predictor.storage.repository import Repository
from nankan_predictor.features.builder import FeatureBuilder
import pandas as pd

repo = Repository()
builder = FeatureBuilder(repo)
X, y = builder.build_training_set("2023-01-01", "2024-12-31", target="win")

missing = (X.isna().sum() / len(X)).sort_values(ascending=False)
print('Missing rate (fraction):')
print(missing.to_string())

# show top missing features
print('\nTop 10 missing features:')
print(missing.head(10).to_string())
