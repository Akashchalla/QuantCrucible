FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py cli.py judge.py config.json protocol-v2.json ./
COPY scripts ./scripts
COPY edge ./edge
COPY web ./web
COPY sql ./sql
RUN useradd --create-home researcher && mkdir private_data .massive_cache && chown -R researcher:researcher /app
USER researcher
EXPOSE 8765
CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "1", "--threads", "4", "--timeout", "90", "app:application"]
