# Usamos Python 3.13 en su versión ligera (slim) para que la imagen no pese 1 GB
FROM python:3.13-slim

# Evitamos que Python escriba archivos .pyc y forzamos salida directa a la consola
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Instalamos dependencias del sistema que AnubisOS necesita
# iptables (para el SOC), sudo (para ejecutar comandos), curl (para instalar uv)
RUN apt-get update && apt-get install -y \
    iptables \
    sudo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalamos "uv" (el gestor de paquetes ultra rápido que usamos)
RUN pip install uv

# Establecemos el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiamos los archivos de configuración de dependencias
COPY pyproject.toml uv.lock* ./

# Instalamos las dependencias en el Python del sistema (usando uv)
# Usamos --system porque estamos dentro de un contenedor aislado
RUN uv pip install --system -e .

# Copiamos el resto del código fuente
COPY core/ ./core/
COPY modules/ ./modules/
COPY src/ ./src/
COPY Main.py ./
COPY config.json ./

# Creamos el directorio de datos y evidencias
RUN mkdir -p data/evidence data/logs

# Exponemos un comando por defecto (abrir AnubisOS)
CMD ["python", "Main.py"]