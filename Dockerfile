# Recount GitHub Action image (the Action's container is the only Docker in the project).
FROM python:3.12-slim
WORKDIR /recount
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf src pyproject.toml README.md
WORKDIR /github/workspace
ENTRYPOINT ["recount", "verify"]
