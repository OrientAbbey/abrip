.PHONY: install dev lint typecheck test demo api front build clean

install:
	pip install -e ".[dev,mrt,live]"

lint:
	ruff check src tests && ruff format --check src tests

typecheck:
	mypy src/abrip/models.py src/abrip/api

test:
	pytest -q --cov=abrip --cov-report=term-missing

demo:
	abrip demo bootstrap

api:
	abrip api serve --reload

front:
	cd frontend && npm install && npm run dev

build:
	cd frontend && npm install && npm run build

pipeline:
	abrip reference sync
	abrip ingest broker --from $(FROM) --to $(TO)
	abrip etl curate --from $(FROM) --to $(TO)
	abrip analytics compute --from $(FROM) --to $(TO)
	abrip detect run --from $(FROM) --to $(TO)

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
