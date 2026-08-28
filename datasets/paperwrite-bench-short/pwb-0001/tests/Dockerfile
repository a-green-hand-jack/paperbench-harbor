FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tests
COPY . /tests/
RUN chmod +x /tests/test.sh

ENTRYPOINT ["/tests/test.sh"]
