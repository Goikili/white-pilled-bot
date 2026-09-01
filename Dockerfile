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

# Desbloquear COMPLETAMENTE la política de seguridad de ImageMagick para MoviePy
RUN rm -f /etc/ImageMagick-6/policy.xml /etc/ImageMagick-7/policy.xml /etc/ImageMagick/policy.xml && \
    mkdir -p /etc/ImageMagick-6 /etc/ImageMagick-7 && \
    echo '<policymap><policy domain="path" rights="read|write" pattern="@*"/><policy domain="resource" name="disk" value="10GiB"/></policymap>' | tee /etc/ImageMagick-6/policy.xml /etc/ImageMagick-7/policy.xml

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "bot.py"]
