# IELTS OS Privacy Notes

## Data stored on device

- Vocabulary progress, saved words, wrong questions, writing drafts, speaking transcripts, learning events, reminders, cached news metadata, saved sentences, and a small local error log.
- Speaking audio is stored in the app's local IndexedDB database.

## Device permissions

- Microphone: used only when the learner starts a speaking recording.
- Notifications: requested only after the learner enables a daily reminder.
- Files: used only when the learner explicitly imports material or a backup.

## Network data

- Guardian Content API: receives a news query; the app stores article metadata and links, not full articles.
- Configured AI service: receives the prompt, tool results, essay, speaking transcript, or compact learning-memory summary needed for the requested feature. Audio files and personal source documents are not included. The model service API key remains on the server and is never stored in the app. A local Ollama/vLLM backend keeps these requests on the machine.

## Production requirements

- Publish a user-facing privacy policy before TestFlight external testing.
- Add account deletion and cloud-data deletion when accounts are enabled.
- Define retention periods for cloud backups, AI inputs, logs, and recordings.
- Restrict the AI service CORS origin, authenticate requests, rate-limit usage, and avoid logging essay/audio content.
- Complete the App Store privacy questionnaire from the final production data flow, not from this development note.
