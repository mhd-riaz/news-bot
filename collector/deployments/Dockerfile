# Build context is the repository root:
#   docker build -f deployments/Dockerfile .

FROM golang:1.27-alpine AS build

WORKDIR /src

# Cache dependencies separately from source so edits do not refetch modules.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG VERSION=dev
RUN mkdir -p /out && \
  for command in ./cmd/*; do \
    name="${command##*/}"; \
    CGO_ENABLED=0 GOOS=linux go build -trimpath \
      -ldflags="-s -w -X main.version=${VERSION}" \
      -o "/out/${name}" "${command}"; \
  done

FROM alpine:3.21

RUN apk add --no-cache ca-certificates && \
  addgroup -S -g 10001 app && \
  adduser -S -u 10001 -G app -H -D app

WORKDIR /app

COPY --from=build /out/ /app/
COPY configs /app/configs

# Never run as root.
USER 10001:10001

EXPOSE 8080

CMD ["/app/api"]
