export interface HumanInputRequest {
	stageId: string;
	agentName: string;
	question: string;
	context: string;
}

export interface HumanInputResponse {
	action: "continue" | "abort";
	message: string;
}

export interface HumanInLoop {
	requestInput(request: HumanInputRequest): Promise<HumanInputResponse>;
}
