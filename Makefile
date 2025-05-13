.PHONY: format format-test check fix clean clean-build clean-pyc clean-test coverage install pylint pylint-quick pyre test publish poetry-check publish isort isort-check docker-push docker-build migrate lint

APP_ENV ?= dev
VERSION := `cat VERSION`
package := hetznerinv
NAMESPACE := hetznerinv

DOCKER_BUILD_ARGS ?= "-q"

all: fix

.PHONY: clear-test-db create-cache-db clean-db .check-clear

help:
	@echo "clean - remove all build, test, coverage and Python artifacts"
	@echo "clean-build - remove build artifacts"
	@echo "clean-pyc - remove Python file artifacts"
	@echo "clean-test - remove test and coverage artifacts"
	@echo "lint - check style with flake8"
	@echo "test - run tests quickly with the default Python"
	@echo "test-all - run tests on every Python version with tox"
	@echo "coverage - check code coverage quickly with the default Python"
	@echo "docs - generate Sphinx HTML documentation, including API docs"
	@echo "release - package and upload a release"
	@echo "dist - package"
	@echo "install - install the package to the active Python's site-packages"
	@echo "migrate - Execute a db migration"

clean: clean-build clean-pyc clean-test

clean-build:
	rm -rf build/ dist/ .eggs/
	find . \( -path "./.venv" -o -path "./.cache" \) -prune -o \
	       \( -name '*.egg-info' -o -name '*.egg' \) -exec rm -rf {} +

clean-pyc:
	rm -f pyrightconfig.json
	find . \( -path "./.venv" -o -path "./.cache" \) -prune -o \
	       \( -name '*.pyc' -o -name '*.pyo' -o -name '*~' -o -name 'flycheck_*' \) -exec rm -f {} +
	find . \( -path "./.venv" -o -path "./.cache" \) -prune -o \
	       \( -name '__pycache__' -o -name '.mypy_cache' -o -name '.pyre' \) -exec rm -rf {} +

clean-test:
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/
	rm -f coverage.xml
	rm -f report.xml

test:
	HETZNERINV_CONFIG=tests/data/test_config.yaml poetry run py.test --cov=$(package) --verbose tests --cov-report=html --cov-report=term --cov-report xml:coverage.xml --cov-report=term-missing --junitxml=report.xml --asyncio-mode=auto

coverage:
	poetry run coverage run --source $(package) setup.py test
	poetry run coverage report -m
	poetry run coverage html
	$(BROWSER) htmlcov/index.html

install: clean
	poetry install

pylint-quick:
	poetry run pylint --rcfile=.pylintrc $(package)  -E -r y

pylint:
	poetry run pylint --rcfile=".pylintrc" $(package)

pyright:
	poetry run pyright
lint: format-test isort-check ruff poetry-check
check: lint pyright

pyre: pyre-check

pyre-check:
	poetry run pyre --noninteractive check 2>/dev/null

format:
	poetry run ruff format $(package)

format-test:
	poetry run ruff format $(package) --check

poetry-check:
	poetry check --lock

publish: clean
	poetry build
	poetry publish

isort:
	poetry run isort .
	poetry run ruff check --select I $(package) tests --fix

isort-check:
	poetry run ruff check --select I $(package) tests
	poetry run isort --diff --check .

ruff:
	poetry run ruff check

fix: format isort
	poetry run ruff check --fix

.ONESHELL:
pyrightconfig:
	jq \
      --null-input \
      --arg venv "$$(basename $$(poetry env info -p))" \
      --arg venvPath "$$(dirname $$(poetry env info -p))" \
      '{ "venv": $$venv, "venvPath": $$venvPath }' \
      > pyrightconfig.json

rename:
	ack hetznerinv -l | xargs -i{} sed -r -i "s/hetznerinv/hetznerinv/g" {}
	ack Hetznerinv -i -l | xargs -i{} sed -r -i "s/Hetznerinv/Hetznerinv/g" {}
	ack HETZNERINV -i -l | xargs -i{} sed -r -i "s/HETZNERINV/HETZNERINV/g" {}

ipython:
	poetry run ipython


CONTAINER_REGISTRY=ghcr.io/ant31/hetznerinv


docker-push-local: docker-build-locall
    docker push $(CONTAINER_REGISTRY):latest

docker-build-local:
    docker build --network=host -t $(CONTAINER_REGISTRY):latest .

docker-push:
	docker buildx build --push -t $(CONTAINER_REGISTRY):latest .

BUMP ?= patch
bump:
	poetry run bump-my-version bump $(BUMP)
