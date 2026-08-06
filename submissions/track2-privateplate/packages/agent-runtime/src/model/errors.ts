export type ModelProviderErrorCode =
  | "MODEL_HTTP_ERROR"
  | "MODEL_RESPONSE_INVALID"
  | "MODEL_TOOL_ARGUMENT_INVALID"
  | "MODEL_NO_TOOL_DECISION_INVALID"
  | "MODEL_FINAL_PROTOCOL_VIOLATION";

export class ModelProviderError extends Error {
  readonly code: ModelProviderErrorCode;

  constructor(code: ModelProviderErrorCode, message: string) {
    super(message);
    this.name = "ModelProviderError";
    this.code = code;
  }
}

export function modelProviderErrorCode(error: unknown): ModelProviderErrorCode {
  return error instanceof ModelProviderError
    ? error.code
    : "MODEL_HTTP_ERROR";
}
