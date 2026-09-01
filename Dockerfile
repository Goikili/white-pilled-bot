FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Instalar ffmpeg, imagemagick y dependencias
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    fonts-freefont-ttf \
    git \
    && rm -rf /var/lib/apt/lists/*

# Eliminar todas las restricciones de seguridad de ImageMagick para MoviePy
RUN sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@\*"/g' /etc/ImageMagick*/*.xml 2>/dev/null || true && \
    sed -i '/pattern="@\*"/d' /etc/ImageMagick*/*.xml 2>/dev/null || true && \
    sed -i 's/<policy domain="coder" rights="none" pattern="MVG" \/>/<policy domain="coder" rights="read|write" pattern="MVG" \/>/g' /etc/ImageMagick*/*.xml 2>/dev/null || true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "bot.py"]
