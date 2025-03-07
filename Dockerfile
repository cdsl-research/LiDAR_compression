# Pythonベースイメージを使用
FROM python:3.9-slim

# 作業ディレクトリを設定
WORKDIR /app

# 必要なファイルをコンテナにコピー
COPY server.py /app/server.py
COPY logs /app/logs


# 依存関係をインストール（必要なら）
# RUN pip install --no-cache-dir -r requirements.txt

# メインサーバーをデフォルトで実行する
CMD ["python", "/app/server.py"]
