FROM golang:1.22 AS build
WORKDIR /src
COPY static-server.go ./
RUN CGO_ENABLED=0 go build -o /poster-web static-server.go

FROM scratch
COPY --from=build /poster-web /poster-web
COPY dist /public
EXPOSE 80
ENTRYPOINT ["/poster-web"]
