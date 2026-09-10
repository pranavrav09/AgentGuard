.PHONY: dev down test test-unit test-policy lint format demo

dev:
	docker compose up --build

down:
	docker compose down --remove-orphans

test: test-unit test-policy

test-unit:
	pytest

test-policy:
	docker compose run --rm opa test /policies -v

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

demo:
	./scripts/demo.sh

