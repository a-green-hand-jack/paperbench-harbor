.PHONY: install lint format papersmith-build papersmith-describe

install:
	python -m pip install -e '.[dev,datasets]'

papersmith-build:
	sh scripts/papersmith-docker.sh build

papersmith-describe:
	PAPERSMITH_NETWORK=none sh scripts/papersmith-docker.sh run --domain physics --run-root /runs/describe --research-type simulation --describe-request

lint:
	ruff check .

format:
	ruff format .
