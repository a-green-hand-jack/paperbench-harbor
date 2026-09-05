FROM node:22-bookworm-slim AS node
FROM ubuntu:24.04

ARG OPENCODE_VERSION=1.18.29
ARG CODEX_VERSION=0.153.4
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential python3 python3-venv \
    poppler-utils latexmk texlive-latex-extra texlive-fonts-recommended \
    texlive-science texlive-xetex texlive-luatex biber \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g opencode-ai@${OPENCODE_VERSION} @openai/codex@${CODEX_VERSION} \
    && npm cache clean --force

# Install dependencies, never the checkout or host configuration, into the image.
COPY pyproject.toml /opt/papersmith-dependencies.toml
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN python -c 'import subprocess,tomllib; p=tomllib.load(open("/opt/papersmith-dependencies.toml","rb"))["project"]; deps=p["dependencies"]+sum((p["optional-dependencies"][k] for k in ("datasets","harbor","sidecar")),[]); subprocess.check_call(["python","-m","pip","install","--no-cache-dir","uv","ruff",*deps])'
# Provider modules may use passwd's home rather than $HOME for canonical paths.
# This identity has no host-home mount; runtime state still uses /state/home.
ARG PAPERSMITH_UID=1000
ARG PAPERSMITH_GID=1000
ARG PAPERSMITH_HOME=/home/user
RUN userdel ubuntu \
    && groupadd --non-unique --gid ${PAPERSMITH_GID} papersmith \
    && useradd --no-create-home --uid ${PAPERSMITH_UID} --gid ${PAPERSMITH_GID} \
        --home-dir "${PAPERSMITH_HOME}" --shell /bin/bash papersmith
ENV PYTHONDONTWRITEBYTECODE=1 UV_NO_SYNC=1 UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/cache/uv XDG_CACHE_HOME=/cache HOME=/state/home \
    OPENCODE_DISABLE_AUTOUPDATE=1
CMD ["bash"]
