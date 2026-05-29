FROM node:20-alpine AS build
WORKDIR /app

# Allow overriding registry at build time, default to a fast CN mirror.
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry ${NPM_REGISTRY}

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html

# nginx.conf listens on 23456 (not the base image's default 80). Declare it so
# `docker inspect` reflects reality; EXPOSE is documentation only.
EXPOSE 23456
