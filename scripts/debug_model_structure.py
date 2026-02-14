#!/usr/bin/env python3
"""モデルの構造を確認"""

import joblib
from pathlib import Path

model_path = Path("data/models/nankan_v1_win.joblib")
if not model_path.exists():
    print(f"Model not found: {model_path}")
else:
    model = joblib.load(model_path)
    print(f"Model type: {type(model)}")
    print(f"Model attributes: {dir(model)}")
    print(f"\nModel object:\n{model}")
    
    # nested check
    if hasattr(model, "named_steps"):
        print(f"\nIt's a Pipeline with steps:")
        for name, step in model.named_steps.items():
            print(f"  {name}: {type(step)}")
            if hasattr(step, "feature_importances_"):
                print(f"    -> has feature_importances_")
    
    if hasattr(model, "steps"):
        print(f"\nSteps:")
        for name, step in model.steps:
            print(f"  {name}: {type(step)}")
            if hasattr(step, "feature_importances_"):
                print(f"    -> has feature_importances_")
