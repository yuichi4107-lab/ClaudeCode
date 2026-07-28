"""確率キャリブレーションモジュール"""

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ProbabilityCalibrator:
    """Calibrate predicted probabilities using Platt scaling or isotonic regression."""

    def __init__(self, method: str = "isotonic"):
        if method not in ("platt", "isotonic"):
            raise ValueError(f"Unknown calibration method: {method}")
        self.method = method
        self.calibrator = None

    def fit(self, y_true: np.ndarray, y_pred_proba: np.ndarray):
        """Fit calibration model on validation predictions.

        Args:
            y_true: Ground truth binary labels.
            y_pred_proba: Raw predicted probabilities.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)

        if self.method == "platt":
            self.calibrator = LogisticRegression(C=1e10, solver="lbfgs")
            self.calibrator.fit(y_pred_proba.reshape(-1, 1), y_true)
        else:
            self.calibrator = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds="clip"
            )
            self.calibrator.fit(y_pred_proba, y_true)

        logger.info("Calibrator fitted (method=%s)", self.method)

    def calibrate(self, y_pred_proba: np.ndarray) -> np.ndarray:
        """Apply calibration to new predictions."""
        if self.calibrator is None:
            raise RuntimeError("Calibrator not fitted. Call fit() first.")

        y_pred_proba = np.asarray(y_pred_proba, dtype=float)

        if self.method == "platt":
            return self.calibrator.predict_proba(
                y_pred_proba.reshape(-1, 1)
            )[:, 1]
        else:
            return self.calibrator.predict(y_pred_proba)

    @staticmethod
    def brier_score(y_true: np.ndarray, y_pred_proba: np.ndarray) -> float:
        """Brier score (lower is better). Range [0, 1]."""
        y_true = np.asarray(y_true, dtype=float)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        return float(np.mean((y_pred_proba - y_true) ** 2))

    @staticmethod
    def expected_calibration_error(
        y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
    ) -> float:
        """Expected Calibration Error (lower is better)."""
        y_true = np.asarray(y_true, dtype=float)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        n = len(y_true)
        if n == 0:
            return 0.0

        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        ece = 0.0

        for i in range(n_bins):
            mask = (y_pred_proba > bin_edges[i]) & (
                y_pred_proba <= bin_edges[i + 1]
            )
            if i == 0:
                mask = (y_pred_proba >= bin_edges[i]) & (
                    y_pred_proba <= bin_edges[i + 1]
                )

            bin_count = mask.sum()
            if bin_count == 0:
                continue

            bin_acc = y_true[mask].mean()
            bin_conf = y_pred_proba[mask].mean()
            ece += (bin_count / n) * abs(bin_acc - bin_conf)

        return float(ece)
