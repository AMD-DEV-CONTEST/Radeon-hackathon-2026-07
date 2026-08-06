# Stage 1: build the jar with Maven (needs the full JDK + Maven Central access)
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
# Cache dependency resolution as its own layer so code-only changes don't
# force a full re-download of the Maven repository.
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B -DskipTests package

# Stage 2: run with just a JRE - no Maven, no source, much smaller image
FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*
RUN useradd --system --create-home appuser
COPY --from=build /app/target/*.jar app.jar
RUN mkdir -p /data/uploads /data/run && chown -R appuser:appuser /app /data
USER appuser
ENV SERVER_PORT=8081
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD wget -qO- http://localhost:${SERVER_PORT}/api/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
