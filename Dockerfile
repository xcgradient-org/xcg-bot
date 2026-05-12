FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

ENV PATH=/app/.venv/bin:$PATH

CMD ["python", "-m", "bot.main"]
