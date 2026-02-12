from setuptools import setup, find_packages

setup(
    name="nankan_predictor",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.0.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.4.0",
        "lightgbm>=4.3.0",
        "joblib>=1.3.0",
        "tqdm>=4.66.0",
        "colorama>=0.4.6",
    ],
    entry_points={
        "console_scripts": [
            "nankan=nankan_predictor.cli.main:main",
        ],
    },
    python_requires=">=3.10",
)
