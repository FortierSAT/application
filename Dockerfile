############################################
# 1) Build Node dependencies for scrapers
############################################
FROM node:18-bullseye-slim AS node-builder
WORKDIR /scraper

# install only package manifests first (layer caching)
COPY core/scrapers/package.json core/scrapers/package-lock.json ./
RUN npm ci

# download browsers + OS deps for Playwright
RUN npx playwright install --with-deps

# copy your scraper scripts
COPY core/scrapers/*.js ./

############################################
# 2) Base Python image (shared layers)
############################################
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# system deps for Chromium, LibreOffice, Node, etc.
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

# bring in both requirements lists
COPY requirements.txt ./

############################################
# 3) Final release image (all deps + code)
############################################
FROM base AS release

# install Python deps for both web & cron
RUN pip install --no-cache-dir -r requirements.txt

# pull in Node scrapers & browsers
COPY --from=node-builder /scraper             /app/core/scrapers
COPY --from=node-builder /root/.cache/ms-playwright /root/.cache/ms-playwright
COPY --from=node-builder /scraper/node_modules      /app/core/scrapers/node_modules

# copy your entire app (webapp/, cronjob/, core/, etc.)
COPY . .

# expose Flask port
EXPOSE 5000

# default: no-op, to be overridden by Render
CMD ["bash", "-lc", "echo \"Override this with your Render start command\""]
