FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY insights ./insights
COPY sql ./sql
RUN pip install --no-cache-dir .

# default job: refresh, then report on the last complete week
CMD ["sh", "-c", "insights refresh && insights report --out /tmp/out"]
