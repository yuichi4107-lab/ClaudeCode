"""モデル基底クラス"""

from abc import ABC, abstractmethod

import numpy as np


class BaseModel(ABC):
    """Abstract base class for all prediction models."""

    @abstractmethod
    def fit(self, X, y, X_val=None, y_val=None):
        """Train the model.

        Args:
            X: Training features.
            y: Training labels.
            X_val: Optional validation features for early stopping.
            y_val: Optional validation labels for early stopping.
        """

    @abstractmethod
    def predict_proba(self, X) -> np.ndarray:
        """Return probability predictions for the positive class.

        Args:
            X: Feature matrix.

        Returns:
            1-D array of predicted probabilities.
        """

    @abstractmethod
    def save(self, path: str):
        """Save model to disk."""

    @abstractmethod
    def load(self, path: str):
        """Load model from disk."""

    @property
    @abstractmethod
    def feature_importances_(self) -> np.ndarray:
        """Return feature importance scores."""
