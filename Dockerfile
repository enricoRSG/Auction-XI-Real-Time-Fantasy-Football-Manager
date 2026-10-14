FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY restore_checkpoint.py ./
ENV AUCTIONXI_DB_PATH=/data/fantacalcio.db PYTHONUNBUFFERED=1 AUCTIONXI_REMOTE_HOST=1
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
