.PHONY: backend frontend zendesk-app evaluate validate docker-config docker-build docker-up docker-down

backend:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy src tests
	uv run pytest -q

frontend:
	npm --prefix frontend run lint
	npm --prefix frontend run test
	npm --prefix frontend run build
	npm --prefix frontend audit

zendesk-app:
	npm --prefix zendesk-app run test
	npm --prefix zendesk-app run build

evaluate:
	uv run copilot-evaluate --output output/golden-evaluation-report.json

validate: backend frontend zendesk-app evaluate docker-config

docker-config:
	docker compose config --quiet

docker-build:
	docker compose build

docker-up:
	docker compose up --detach --wait

docker-down:
	docker compose down
