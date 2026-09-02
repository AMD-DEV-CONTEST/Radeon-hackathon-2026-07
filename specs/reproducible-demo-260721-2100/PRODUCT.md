# Reproducible MVP Demonstration

## Background

The MVP must be reproducible on a fresh AMD cloud instance and demonstrable
without manually creating hidden files or relying on a developer workstation.

## User-visible behavior

- A README documents environment setup, dual llama-server endpoints, API and
  workbench startup, demo uploads, and expected output artifacts.
- Versioned sample evidence and a task CSV provide a safe repeatable demo.
- The cloud smoke script verifies the chat service and all report artifacts.

## Non-goals

- This does not package a container image or replace the cloud platform's
  instance lifecycle instructions.
