FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p static/uploads logs

ENV BIND=0.0.0.0:8000
EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn_conf.py", "run:app"]
