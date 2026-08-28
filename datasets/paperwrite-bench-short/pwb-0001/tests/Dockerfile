FROM python:3.11-slim

WORKDIR /tests
COPY tests/ /tests/
RUN chmod +x /tests/test.sh

ENTRYPOINT ["/tests/test.sh"]
