# ---- Build stage ----
ARG BUILD_IMAGE=maven:3.9-eclipse-temurin-21
FROM ${BUILD_IMAGE} AS build
WORKDIR /app
COPY pom.xml .
# Download dependencies first to cache them
RUN mvn -B dependency:go-offline

# Copy source and build
COPY src ./src
RUN mvn -B package -DskipTests

# ---- Runtime stage ----
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# Copy the built jar from the build stage
COPY --from=build /app/target/parceltracking-0.0.1-SNAPSHOT.jar /app/parceltracking.jar

# Expose port
EXPOSE 8080

# Default command
ENTRYPOINT ["java", "-jar", "parceltracking.jar"]