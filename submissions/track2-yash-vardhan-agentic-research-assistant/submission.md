\# Agentic Research Assistant — Track 2 Submission



\*\*Author:\*\* Yash Vardhan



\*\*Project repo:\*\* https://github.com/Yashhh0602/agentic-research-amd-scaffold



\*\*Demo video:\*\* \[ADD YOUR VIDEO LINK HERE — upload to YouTube/Drive first]



\*\*Project Specification Document:\*\* https://github.com/Yashhh0602/agentic-research-amd-scaffold/blob/main/docs/Project\_Specification.pdf



\## Summary



A multi-agent research assistant with four agents (Retriever, Reasoning, Executor, Synthesizer) that collaborate to answer technical questions using RAG over a pgvector knowledge base, tool use (Tavily web search, sandboxed code execution), and LLM synthesis on AMD ROCm hardware via vLLM.



The core contribution is a dependency-aware orchestrator that runs independent agents (Retriever + Reasoning) concurrently rather than strictly sequentially, benchmarked live on an AMD Radeon Cloud pod:



\- \*\*Agent-level concurrency:\*\* 1.17x speedup (sequential 21.4s vs concurrent 18.4s)

\- \*\*Throughput under concurrent multi-user load:\*\* 4.08x speedup (125.6s vs 30.8s for 5 simultaneous queries)



Full architecture, benchmarks, and an honest account of a model-routing bug fix are documented in the project README and the attached Project Specification Document.

