"""Local process runtime for cross-platform agent execution."""

__all__ = [
    "NativeAgentRuntimeLauncher",
    "NativeAgentRuntimePlan",
    "NativeAgentRuntimeHandle",
    "NativeDependencyPool",
    "AgentRuntimeLaunchError",
]


def __getattr__(name: str):
    if name in {"NativeAgentRuntimeLauncher", "NativeAgentRuntimePlan", "AgentRuntimeLaunchError"}:
        from .launcher import AgentRuntimeLaunchError, NativeAgentRuntimeLauncher, NativeAgentRuntimePlan
        return {
            "NativeAgentRuntimeLauncher": NativeAgentRuntimeLauncher,
            "NativeAgentRuntimePlan": NativeAgentRuntimePlan,
            "AgentRuntimeLaunchError": AgentRuntimeLaunchError,
        }[name]
    if name == "NativeAgentRuntimeHandle":
        from .handle import NativeAgentRuntimeHandle
        return NativeAgentRuntimeHandle
    if name == "NativeDependencyPool":
        from .dependency_pool import NativeDependencyPool
        return NativeDependencyPool
    raise AttributeError(name)
