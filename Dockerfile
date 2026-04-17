# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

# Ensure scripts in .local/bin are in PATH
ENV PATH=/root/.local/bin:$PATH

CMD ["python", "main.py"]
