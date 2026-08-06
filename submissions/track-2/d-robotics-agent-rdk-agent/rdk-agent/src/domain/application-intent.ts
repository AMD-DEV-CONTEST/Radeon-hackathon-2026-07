const readOnlyRequestMarkers = [
	/[?？]\s*$/,
	/(哪些|什么|怎么|怎样|如何|为什么|是否|能否|可以吗|能不能|有没有|支持吗)/,
	/(查看|查询|列出|介绍|说明|告诉我|了解).*(能力|命令|状态|配置|列表|Skill|skill|动作)/,
	/(当前|已经|已).*(加载|配置|支持)/,
	/(加载|配置|支持).*(哪些|什么|情况|状态)/,
	/^\s*(?:what|which|how|why|whether|can|could|would|is|are)\b/i,
	/^\s*(?:please\s+)?(?:show(?:\s+me)?|list|view|check|get|describe|explain|tell\s+me)\b[^\n]*\b(?:actions?|capabilit(?:y|ies)|commands?|configuration|config|help|skills?|status|supported|available)\b/i,
	/^\s*(?:please\s+)?(?:show(?:\s+me)?|list|describe|explain|tell\s+me)\b[^\n]*\b(?:what|everything)\s+(?:you|it|the\s+robot)\s+can\s+do\b/i,
	/^\s*(?:please\s+)?(?:do|does)\s+(?:you|it|this|that|the\s+(?:robot|system|agent))\b[^\n]*\b(?:support|show|list|have|know|offer|provide)\b/i,
	/^\s*(?:available|supported|loaded|configured)\b[^\n]*\b(?:actions?|capabilit(?:y|ies)|commands?|skills?)\b/i,
	/^\s*(?:please\s+)?(?:help|--help|status)\s*[.!?]*\s*$/i,
];

/** Queries are read-only even in robot-application mode; all other imperative text remains action-authorized. */
export function isReadOnlyApplicationRequest(request: string): boolean {
	const normalized = request.trim();
	return readOnlyRequestMarkers.some((pattern) => pattern.test(normalized));
}
