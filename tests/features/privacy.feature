Feature: Privacy gating
  Bunker keeps all data on the user's machine: write tools are gated behind
  explicit human consent, and no inference or retrieval path may dial out to
  a non-loopback host. This feature pins those guarantees as executable
  acceptance criteria.

  Scenario: Write tool requires explicit consent
    Given a permission controller with demo mode disabled
    When the agent requests approval for the "file_write" tool
    Then the request is denied
    And the denial is recorded in the permission history

    When the agent tries to auto-approve "file_write"
    Then "file_write" still requires explicit approval
    And a fresh "file_write" request is denied again

  Scenario: No cloud fallback under any path
    Given a guarded socket that rejects non-loopback connections
    And a local vector store containing one passage about the Eiffel Tower
    And the Bunker multi-hop RAG program with 1 hop over that store
    When the RAG pipeline answers "Where is the Eiffel Tower?"
    Then every network connection attempted targets loopback only
    And the default inference backend targets localhost
    And the answer is produced from local context only
