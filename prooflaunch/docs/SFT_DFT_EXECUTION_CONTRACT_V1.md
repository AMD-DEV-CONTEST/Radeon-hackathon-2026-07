# Multimodal Curriculum SFT/DFT Execution Contract V1

This contract implements the executable, test-blind mechanics for canonical
TODO 0651–0700 without presenting a controlled fixture as trained-model
evidence.

The curriculum contains fourteen ordered GTM stages from Evidence through
Stop, followed across nine input phases from short text through cross-channel
tasks. Every stage declares required outputs and rejects unsupported claims,
hidden reasoning and unbounded tool actions.

Claim, locator, SMP, RTB, Big Idea, JSON and Stop tokens receive explicit
positive emphasis. Unsafe actions receive zero positive-target weight and a
separate unlikelihood objective; they are not silently taught at a smaller
positive weight.

Ordinary SFT is the unweighted control. DFT enables token weighting plus the
negative objective. Both are completion-only and test-blind. Stage adapters,
data revisions and metrics are content-addressed in a previous-stage hash
chain, enabling exact rollback and multi-stage replay.

The generated planned card deliberately leaves SFT/DFT metrics, random-order
and reverse-curriculum controls, curriculum gain and selected adapter as
`null`. TODO 0682–0689 and 0695–0700 therefore remain open until real
Radeon training, frozen comparisons, significance testing, reports and an
adapter checkpoint are observed.
