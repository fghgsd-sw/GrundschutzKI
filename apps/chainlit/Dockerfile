FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1. Nur Abhängigkeitsdateien kopieren (maximaler Cache-Effekt)
COPY pyproject.toml ./
# Falls du requirements.txt verwendest, auch:
# COPY requirements.txt ./

# 2. Abhängigkeiten installieren (wird nur neu ausgeführt, wenn sich pyproject.toml ändert)
RUN pip install --upgrade pip && pip install .

# 3. Restlichen Code kopieren (schnell, wenn sich nur Code ändert)
COPY . .

EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
