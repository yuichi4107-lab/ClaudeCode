"""FX自動売買システム セットアップ"""

from setuptools import setup, find_packages

setup(
    name="fx_trader",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.4.0",
        "lightgbm>=4.3.0",
        "joblib>=1.3.0",
    ],
    entry_points={
        "console_scripts": [
            "fxtrade=fx_trader.cli.main:main",
        ],
    },
    python_requires=">=3.10",
)
