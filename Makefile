.PHONY: install lint format papersmith-build papersmith-describe

install:
	sh install.sh

papersmith-build:
	sh docker/e2e.sh build

papersmith-describe:
	PAPERSMITH_NETWORK=none sh docker/e2e.sh run 'Discover scientific papers on any topic' --count 5 --output /runs/describe --describe-request --json --headless

lint:
	ruff check .

format:
	ruff format .
