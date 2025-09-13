FROM python:3.11-slim

WORKDIR /app

# Copie et installation des dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code source
COPY app.py .

# Variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Exposition du port
EXPOSE 8080

# Démarrage avec uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
