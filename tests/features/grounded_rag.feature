Feature: Grounded multi-hop RAG
  Bunker answers document questions from passages retrieved by the local
  ChromaDB store and cites the passages it relies on. When the retrieved
  context cannot support an answer, the pipeline refuses to fabricate one.

  Each scenario runs against the live localhost model when it is serving
  (statistical 10-run assertions, matching tests/test_integration_qwen.py);
  otherwise it runs the deterministic offline pipeline with a scripted model,
  so this suite is runnable on any machine.

  Scenario: Multi-hop question draws from two passages
    Given a local vector store containing passages about the Eiffel Tower and Paris
    And the Bunker multi-hop RAG program with 2 hops over that store
    When a user asks "Where is the Eiffel Tower and what is the capital of France?"
    Then the answer is grounded in at least two distinct passages
    And the answer cites the passages it relies on

  Scenario: Insufficient context is reported honestly
    Given a local vector store with no passages matching the question
    And the Bunker multi-hop RAG program with 1 hop over that store
    When a user asks "Who invented the telephone?"
    Then the pipeline refuses to fabricate an answer
