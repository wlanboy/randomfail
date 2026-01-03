FROM python:3.12-slim

WORKDIR /app

RUN pip install fastapi uvicorn

COPY index.html .
COPY main.py .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
