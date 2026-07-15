run:
	uvicorn main:app --reload

test:
	python3 -m unittest discover -s tests -p "test_*.py"

docker-build:
	docker build -t class-swap-app .

docker-run:
	docker run --rm -p 8000:8000 --env-file .env -v class-swap-data:/app/data class-swap-app
