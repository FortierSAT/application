#######################################
# 1) Build Node dependencies for scrapers
#######################################
FROM node:18-bullseye-slim AS node-builder

# work in a temporary directory
WORKDIR /scraper

# install only package manifests first, for layer caching
COPY core/scrapers/package.json core/scrapers/package-lock.json ./
RUN npm ci

# download Chromium, Firefox & WebKit + OS deps
RUN npx playwright install --with-deps

# copy your scraper scripts into the builder
COPY core/scrapers/escreen.js core/scrapers/*.js ./

#######################################
# 2) Base Python image (common layers)
#######################################
FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# install system packages (Chromium for Puppeteer, LibreOffice, Node for any in-Python builds)
RUN apt-get update && apt-get install -y \
      chromium \
      gconf-service libasound2 libatk1.0-0 libatk-bridge2.0-0 \
      libc6 libcairo2 libexpat1 libfontconfig1 libgcc1 libgconf-2-4 \
      libgdk-pixbuf2.0-0 libglib2.0-0 libgtk-3-0 libnspr4 libpango-1.0-0 \
      libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
      libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
      ca-certificates fonts-liberation libnss3 lsb-release xdg-utils \
      curl gnupg \
      libreoffice-core libreoffice-calc fonts-dejavu-core \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# copy in your split requirements lists
COPY requirements-web.txt requirements-cron.txt ./

#######################################
# 3) Web image
#######################################
FROM base AS web

# install only the Flask/web dependencies
RUN pip install --no-cache-dir -r requirements-web.txt

# bring in all your application code
COPY . .

# open the Flask port
EXPOSE 5000

# default entrypoint for your web service
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "webapp.wsgi:app"]

#######################################
# 4) Cron image
#######################################
FROM base AS cron

# install only the cron pipeline’s Python deps
RUN pip install --no-cache-dir -r requirements-cron.txt

# copy in your full app (so cronjob/, core/, etc. are present)
COPY . .

# copy the JS scrapers code and Node deps from the builder
COPY core/scrapers       /app/core/scrapers
COPY --from=node-builder /scraper/node_modules /app/core/scrapers/node_modules

# copy the Playwright browser binaries too
COPY --from=node-builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# default command to run your scraping pipeline
CMD ["python", "-m", "cronjob.main"]