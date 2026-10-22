# Build context is the repository root:
#   docker build -f deployments/Dockerfile .

FROM golang:1.26-alpine AS build

WORKDIR /src

# Cache dependencies separately from source so edits do not refetch modules.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG VERSION=dev
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/api ./cmd/api && \
  CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/migrate ./cmd/migrate && \
  CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/seed ./cmd/seed && \
  CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/scrape ./cmd/scrape

FROM alpine:3.21

RUN apk add --no-cache ca-certificates && \
  addgroup -S -g 10001 app && \
  adduser -S -u 10001 -G app -H -D app

WORKDIR /app

COPY --from=build /out/api /app/api
COPY --from=build /out/migrate /app/migrate
COPY --from=build /out/seed /app/seed
COPY --from=build /out/scrape /app/scrape
COPY configs /app/configs

# Never run as root.
USER 10001:10001

EXPOSE 8080

ENTRYPOINT ["/app/api"]
