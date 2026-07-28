FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Tokyo
RUN ln -snf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime && echo Asia/Tokyo > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY scripts/ scripts/
COPY data/ data/
COPY results/ results/

# ディレクトリ準備
RUN mkdir -p data/signals data/ohlcv logs/forward results/forward

CMD ["python", "-m", "src.forward.forward_runner", "--exchange", "saxo_sim", "--dry-run"]
