FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libxcb1 libx11-6 libxext6 libxrender1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Install deps only (cached unless pyproject.toml changes)
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install $(python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(' '.join(d['project']['dependencies']))")

# 2) Copy app code + editable install (fast, deps already cached)
COPY . /app
RUN pip install --no-deps -e .

# 3) Pre-download Docling OCR models so first upload is fast
# 3) Pre-download RapidOCR models (torch backend, ~40 MB) so they're cached in the image
RUN python -c "from rapidocr import RapidOCR; engine = RapidOCR(engine_type='torch'); print('RapidOCR torch models cached')"

EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
