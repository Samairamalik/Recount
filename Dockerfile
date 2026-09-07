# Recount GitHub Action image (spec §2.5: the Action's container is the only Docker).
FROM python:3.12-slim
WORKDIR /recount
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src pyproject.toml README.md
WORKDIR /github/workspace
ENTRYPOINT ["recount", "verify"]
