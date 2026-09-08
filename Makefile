.PHONY: install test demo run fmt

install:
	pip install -r requirements-dev.txt

test:
	pytest

demo:
	python chat.py --demo --offline --db :memory:

run:
	uvicorn app.main:app --reload --port 8000

fmt:
	ruff check --fix . && ruff format .
