"""Unified error codes for the Office Agent API (Stage E).

Every public API endpoint returns a structured error containing an
``error_code`` enum member.  All codes are defined here so the frontend can
rely on stable identifiers.
"""

from __future__ import annotations

APP_ERROR_CODES: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------
    # Generic
    # ------------------------------------------------------------------
    "INTERNAL_ERROR": {
        "code": "INTERNAL_ERROR",
        "message": "An internal server error occurred.",
        "user_message": "服务内部错误，请稍后重试。",
    },
    "NOT_FOUND": {
        "code": "NOT_FOUND",
        "message": "The requested resource was not found.",
        "user_message": "请求的资源不存在。",
    },
    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------
    "PROJECT_NOT_FOUND": {
        "code": "PROJECT_NOT_FOUND",
        "message": "Project does not exist.",
        "user_message": "项目不存在。",
    },
    "PROJECT_ID_INVALID": {
        "code": "PROJECT_ID_INVALID",
        "message": "Project ID format is invalid.",
        "user_message": "项目 ID 格式无效，请使用小写字母、数字和连字符。",
    },
    "PROJECT_ALREADY_EXISTS": {
        "code": "PROJECT_ALREADY_EXISTS",
        "message": "A project with that ID already exists.",
        "user_message": "该 ID 的项目已存在。",
    },
    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    "RUN_NOT_FOUND": {
        "code": "RUN_NOT_FOUND",
        "message": "Run does not exist.",
        "user_message": "运行记录不存在。",
    },
    "RUN_ALREADY_EXECUTED": {
        "code": "RUN_ALREADY_EXECUTED",
        "message": "Run already executed; cannot execute again.",
        "user_message": "该运行记录已执行，不能重复执行。",
    },
    "RUN_ALREADY_CANCELLED": {
        "code": "RUN_ALREADY_CANCELLED",
        "message": "Run has already been cancelled.",
        "user_message": "该运行记录已被取消。",
    },
    "RUN_CANCEL_TOO_LATE": {
        "code": "RUN_CANCEL_TOO_LATE",
        "message": "Cannot cancel a run that has already completed or failed.",
        "user_message": "无法取消已完成或失败的运行。",
    },
    "RUN_WRONG_STATUS": {
        "code": "RUN_WRONG_STATUS",
        "message": "Run is not in a valid state for this operation.",
        "user_message": "运行状态不允许此操作。",
    },
    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------
    "FILE_TOO_LARGE": {
        "code": "FILE_TOO_LARGE",
        "message": "Uploaded file exceeds the maximum allowed size.",
        "user_message": "上传文件超过大小限制。",
    },
    "FILE_EXTENSION_NOT_ALLOWED": {
        "code": "FILE_EXTENSION_NOT_ALLOWED",
        "message": "File extension is not in the allowed list.",
        "user_message": "不支持的文件类型。",
    },
    "FILE_MIME_MISMATCH": {
        "code": "FILE_MIME_MISMATCH",
        "message": "File MIME type does not match its extension.",
        "user_message": "文件类型与扩展名不匹配。",
    },
    "FILE_NAME_TOO_LONG": {
        "code": "FILE_NAME_TOO_LONG",
        "message": "Filename exceeds the maximum allowed length.",
        "user_message": "文件名过长。",
    },
    "FILE_EMPTY": {
        "code": "FILE_EMPTY",
        "message": "Uploaded file is empty (zero bytes).",
        "user_message": "上传文件为空。",
    },
    "FILE_VIRUS_DETECTED": {
        "code": "FILE_VIRUS_DETECTED",
        "message": "Virus scan detected a potential threat.",
        "user_message": "文件病毒扫描未通过。",
    },
    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    "VALIDATION_ERROR": {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed.",
        "user_message": "请求参数校验失败。",
    },
    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    "CLEANUP_PARTIAL_FAILURE": {
        "code": "CLEANUP_PARTIAL_FAILURE",
        "message": "Cleanup completed with some errors.",
        "user_message": "清理任务部分失败。",
    },
    # ------------------------------------------------------------------
    # Phase F — Task lifecycle
    # ------------------------------------------------------------------
    "TASK_NOT_FOUND": {
        "code": "TASK_NOT_FOUND",
        "message": "Task does not exist.",
        "user_message": "任务不存在。",
    },
    "TASK_INVALID_TRANSITION": {
        "code": "TASK_INVALID_TRANSITION",
        "message": "Invalid task status transition.",
        "user_message": "无效的任务状态变更。",
    },
    "TASK_CANCELLED_FINAL": {
        "code": "TASK_CANCELLED_FINAL",
        "message": "A cancelled task cannot be reactivated.",
        "user_message": "已取消的任务无法重新激活。",
    },
    "CONFIRMATION_NOT_FOUND": {
        "code": "CONFIRMATION_NOT_FOUND",
        "message": "Confirmation request not found.",
        "user_message": "确认请求不存在。",
    },
    "CONFIRMATION_ALREADY_PROCESSED": {
        "code": "CONFIRMATION_ALREADY_PROCESSED",
        "message": "Confirmation request already processed.",
        "user_message": "该确认请求已被处理。",
    },
    "IMPORT_FILE_UNSUPPORTED": {
        "code": "IMPORT_FILE_UNSUPPORTED",
        "message": "Unsupported file format for import. Only CSV and XLSX are supported.",
        "user_message": "不支持的文件格式，仅支持 CSV 和 XLSX。",
    },
    "IMPORT_PARSE_ERROR": {
        "code": "IMPORT_PARSE_ERROR",
        "message": "Failed to parse the import file.",
        "user_message": "文件解析失败，请检查文件格式。",
    },
    "TASK_ALREADY_EXISTS": {
        "code": "TASK_ALREADY_EXISTS",
        "message": "A task with this ID already exists.",
        "user_message": "该 ID 的任务已存在。",
    },
    # ------------------------------------------------------------------
    # Stage G — Risk & Knowledge Monitoring
    # ------------------------------------------------------------------
    "RISK_RULE_NOT_FOUND": {
        "code": "RISK_RULE_NOT_FOUND",
        "message": "Risk rule does not exist.",
        "user_message": "风险规则不存在。",
    },
    "RISK_RECORD_NOT_FOUND": {
        "code": "RISK_RECORD_NOT_FOUND",
        "message": "Risk record does not exist.",
        "user_message": "风险记录不存在。",
    },
    "RISK_SCAN_FAILED": {
        "code": "RISK_SCAN_FAILED",
        "message": "Risk scan execution failed.",
        "user_message": "风险扫描执行失败。",
    },
    "DOC_VERSION_NOT_FOUND": {
        "code": "DOC_VERSION_NOT_FOUND",
        "message": "Document version record does not exist.",
        "user_message": "文档版本记录不存在。",
    },
    "BENCHMARK_RUN_FAILED": {
        "code": "BENCHMARK_RUN_FAILED",
        "message": "Quality benchmark evaluation failed.",
        "user_message": "质量基准评估失败。",
    },
    "BENCHMARK_DATASET_EMPTY": {
        "code": "BENCHMARK_DATASET_EMPTY",
        "message": "Quality benchmark dataset is empty.",
        "user_message": "质量基准数据集为空。",
    },
    "IMPACT_ANALYSIS_FAILED": {
        "code": "IMPACT_ANALYSIS_FAILED",
        "message": "Change impact analysis failed.",
        "user_message": "变更影响分析失败。",
    },
    # ------------------------------------------------------------------
    # Phase H — Team Collaboration
    # ------------------------------------------------------------------
    "AUTH_INVALID_CREDENTIALS": {
        "code": "AUTH_INVALID_CREDENTIALS",
        "message": "Invalid username or password.",
        "user_message": "用户名或密码错误。",
    },
    "AUTH_TOKEN_EXPIRED": {
        "code": "AUTH_TOKEN_EXPIRED",
        "message": "Authentication token has expired.",
        "user_message": "认证已过期，请重新登录。",
    },
    "AUTH_TOKEN_MISSING": {
        "code": "AUTH_TOKEN_MISSING",
        "message": "Authentication token is missing from request.",
        "user_message": "缺少认证信息，请先登录。",
    },
    "AUTH_TOKEN_INVALID": {
        "code": "AUTH_TOKEN_INVALID",
        "message": "Authentication token is invalid.",
        "user_message": "认证信息无效。",
    },
    "ACCESS_DENIED": {
        "code": "ACCESS_DENIED",
        "message": "You do not have permission to perform this action.",
        "user_message": "您没有权限执行此操作。",
    },
    "ACCESS_DENIED_PROJECT": {
        "code": "ACCESS_DENIED_PROJECT",
        "message": "You do not have access to this project.",
        "user_message": "您没有访问此项目的权限。",
    },
    "ACCESS_DENIED_FILE_DOWNLOAD": {
        "code": "ACCESS_DENIED_FILE_DOWNLOAD",
        "message": "You do not have permission to download files from this project.",
        "user_message": "您没有下载该项目文件的权限。",
    },
    "USER_NOT_FOUND": {
        "code": "USER_NOT_FOUND",
        "message": "User does not exist.",
        "user_message": "用户不存在。",
    },
    "USER_NOT_IN_PROJECT": {
        "code": "USER_NOT_IN_PROJECT",
        "message": "User is not a member of this project.",
        "user_message": "用户不是该项目的成员。",
    },
    "MEMBER_ALREADY_EXISTS": {
        "code": "MEMBER_ALREADY_EXISTS",
        "message": "User is already a member of this project.",
        "user_message": "用户已是该项目成员。",
    },
    "COMMENT_NOT_FOUND": {
        "code": "COMMENT_NOT_FOUND",
        "message": "Comment does not exist.",
        "user_message": "评论不存在。",
    },
    "NOTIFICATION_NOT_FOUND": {
        "code": "NOTIFICATION_NOT_FOUND",
        "message": "Notification does not exist.",
        "user_message": "通知不存在。",
    },
    "REPORT_DRAFT_NOT_FOUND": {
        "code": "REPORT_DRAFT_NOT_FOUND",
        "message": "Report draft does not exist.",
        "user_message": "报告草稿不存在。",
    },
    "REPORT_ALREADY_SUBMITTED": {
        "code": "REPORT_ALREADY_SUBMITTED",
        "message": "Report has already been submitted for approval.",
        "user_message": "报告已提交审批。",
    },
    "REPORT_EXPORT_FAILED": {
        "code": "REPORT_EXPORT_FAILED",
        "message": "Failed to export the report.",
        "user_message": "报告导出失败。",
    },
    "RISK_ASSIGNMENT_FAILED": {
        "code": "RISK_ASSIGNMENT_FAILED",
        "message": "Risk assignment failed.",
        "user_message": "风险分配失败。",
    },
    "RISK_LIFECYCLE_INVALID": {
        "code": "RISK_LIFECYCLE_INVALID",
        "message": "Invalid risk lifecycle transition.",
        "user_message": "无效的风险生命周期变更。",
    },
    # ------------------------------------------------------------------
    # Stage I — External Integrations
    # ------------------------------------------------------------------
    "INTEGRATION_EMAIL_FAILED": {
        "code": "INTEGRATION_EMAIL_FAILED",
        "message": "Email delivery failed.",
        "user_message": "邮件发送失败。",
    },
    "INTEGRATION_WEBHOOK_FAILED": {
        "code": "INTEGRATION_WEBHOOK_FAILED",
        "message": "Webhook delivery failed.",
        "user_message": "Webhook 投递失败。",
    },
    "INTEGRATION_SCM_FAILED": {
        "code": "INTEGRATION_SCM_FAILED",
        "message": "SCM operation failed.",
        "user_message": "SCM 操作失败。",
    },
    "INTEGRATION_RATE_LIMITED": {
        "code": "INTEGRATION_RATE_LIMITED",
        "message": "Integration rate limit exceeded.",
        "user_message": "集成调用频率超限。",
    },
    "INTEGRATION_CONFIRMATION_REQUIRED": {
        "code": "INTEGRATION_CONFIRMATION_REQUIRED",
        "message": "Human confirmation is required for this action.",
        "user_message": "该操作需要人工确认。",
    },
    "AUTOMATION_TASK_NOT_FOUND": {
        "code": "AUTOMATION_TASK_NOT_FOUND",
        "message": "Automation task does not exist.",
        "user_message": "自动化任务不存在。",
    },
    "AUTOMATION_TASK_ALREADY_PAUSED": {
        "code": "AUTOMATION_TASK_ALREADY_PAUSED",
        "message": "Automation task is already paused.",
        "user_message": "自动化任务已暂停。",
    },
    "AUTOMATION_TASK_ALREADY_ACTIVE": {
        "code": "AUTOMATION_TASK_ALREADY_ACTIVE",
        "message": "Automation task is already active.",
        "user_message": "自动化任务已在运行中。",
    },
    "TOKEN_NOT_FOUND": {
        "code": "TOKEN_NOT_FOUND",
        "message": "Integration token not found.",
        "user_message": "集成令牌不存在。",
    },
    "TOKEN_INVALID": {
        "code": "TOKEN_INVALID",
        "message": "Integration token is invalid or expired.",
        "user_message": "集成令牌无效或已过期。",
    },
    "TOKEN_ENCRYPTION_FAILED": {
        "code": "TOKEN_ENCRYPTION_FAILED",
        "message": "Token encryption/decryption failed.",
        "user_message": "令牌加解密失败。",
    },
    # ------------------------------------------------------------------
    # Stage J — Production & AMD Radeon Optimization
    # ------------------------------------------------------------------
    "CONCURRENCY_LIMIT_EXCEEDED": {
        "code": "CONCURRENCY_LIMIT_EXCEEDED",
        "message": "Global or per-project concurrency limit exceeded.",
        "user_message": "并发调用超出限制，请稍后重试。",
    },
    "QUEUE_TIMEOUT": {
        "code": "QUEUE_TIMEOUT",
        "message": "Task waited too long in the queue and timed out.",
        "user_message": "任务排队超时，请稍后重试。",
    },
    "LLM_CALL_CANCELLED": {
        "code": "LLM_CALL_CANCELLED",
        "message": "The LLM call was cancelled.",
        "user_message": "模型调用已被取消。",
    },
    "EMBEDDING_SERVICE_UNAVAILABLE": {
        "code": "EMBEDDING_SERVICE_UNAVAILABLE",
        "message": "Embedding model service is not reachable.",
        "user_message": "向量模型服务不可用。",
    },
    "CACHE_INVALID_KEY": {
        "code": "CACHE_INVALID_KEY",
        "message": "Cache key is invalid or malformed.",
        "user_message": "缓存键无效。",
    },
    "BACKUP_FAILED": {
        "code": "BACKUP_FAILED",
        "message": "Backup operation failed.",
        "user_message": "备份操作失败。",
    },
    "RECOVERY_FAILED": {
        "code": "RECOVERY_FAILED",
        "message": "Recovery operation failed.",
        "user_message": "恢复操作失败。",
    },
    "BACKUP_NOT_FOUND": {
        "code": "BACKUP_NOT_FOUND",
        "message": "Backup does not exist.",
        "user_message": "备份文件不存在。",
    },
    "HEALTH_DEGRADED": {
        "code": "HEALTH_DEGRADED",
        "message": "One or more health checks indicate degradation.",
        "user_message": "服务健康状况异常。",
    },
    "HEALTH_CRITICAL": {
        "code": "HEALTH_CRITICAL",
        "message": "One or more health checks indicate critical failure.",
        "user_message": "服务健康严重异常。",
    },
    "BENCHMARK_NOT_INITIALIZED": {
        "code": "BENCHMARK_NOT_INITIALIZED",
        "message": "Benchmark data has not been collected.",
        "user_message": "尚未收集基准测试数据。",
    },
    "STRESS_TEST_INVALID_PARAMS": {
        "code": "STRESS_TEST_INVALID_PARAMS",
        "message": "Stress test parameters are invalid.",
        "user_message": "压测参数无效。",
    },
}


def get_error(code: str, **detail_kvs: str) -> dict[str, str]:
    """Return a structured error dict for the given error code.

    Args:
        code: An ``APP_ERROR_CODES`` key (e.g. ``"FILE_TOO_LARGE"``).
        **detail_kvs: Extra key/value pairs merged into ``details``.

    Returns:
        A dict with ``error_code``, ``message``, ``user_message``, and
        optional ``details``.
    """
    entry = APP_ERROR_CODES.get(code, APP_ERROR_CODES["INTERNAL_ERROR"])
    result: dict[str, str] = {
        "error_code": entry["code"],
        "message": entry["message"],
        "user_message": entry["user_message"],
    }
    if detail_kvs:
        result["details"] = detail_kvs  # type: ignore[assignment]
    return result
