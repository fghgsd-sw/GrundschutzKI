FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first → cached unless pyproject.toml changes
COPY pyproject.toml /app/
RUN pip install --upgrade pip \
    && pip install -e .

# App code + static assets last → fast rebuilds on CSS/JS changes
COPY . /app

EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
