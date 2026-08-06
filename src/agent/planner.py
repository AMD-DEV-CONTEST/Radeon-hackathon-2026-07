import json
import logging
import re

logger = logging.getLogger(__name__)

class TaskPlanner:
    """Decomposes complex user requests into ordered subtasks."""
    
    def __init__(self, model_manager):
        """
        Initializes the TaskPlanner.
        
        Args:
            model_manager: The model manager for generating plans.
        """
        self.model_manager = model_manager
    
    def plan(self, user_request: str, available_tools: list[dict]) -> list[dict]:
        """
        Creates a plan to address the user request using available tools.
        
        Args:
            user_request (str): The user's query or instruction.
            available_tools (list[dict]): A list of available tools and their schemas.
            
        Returns:
            list[dict]: A list of structured steps.
        """
        prompt_messages = self._build_planning_prompt(user_request, available_tools)
        
        try:
            response = self.model_manager.generate(prompt_messages)
            plan = self._parse_plan(response)
            if not plan:
                logger.warning("Failed to parse plan, falling back to single step.")
                return [{"step": 1, "action": "direct_execution", "tool": "None", "rationale": "Fallback to direct execution."}]
            return plan
        except Exception as e:
            logger.error(f"Error during planning: {e}")
            return [{"step": 1, "action": "direct_execution", "tool": "None", "rationale": "Fallback due to planning error."}]
    
    def _build_planning_prompt(self, user_request: str, available_tools: list[dict]) -> list[dict]:
        """
        Constructs the prompt for the planning model.
        
        Args:
            user_request (str): The user's query.
            available_tools (list[dict]): The available tools.
            
        Returns:
            list[dict]: The messages for the chat model.
        """
        tool_descriptions = "\n".join([f"- {t['name']}: {t['description']}" for t in available_tools])
        
        system_prompt = f"""You are an AI task planner. Given a user request and a list of available tools, create a step-by-step plan.
Output the plan as a numbered list where each item is a JSON object with the following keys:
- "step": The step number (integer)
- "action": A short description of the action
- "tool": The primary tool to be used for this step
- "rationale": Why this step is necessary

Available Tools:
{tool_descriptions}

Example Output:
1. {{"step": 1, "action": "search_db", "tool": "rag_search", "rationale": "Need to find relevant documents."}}
2. {{"step": 2, "action": "summarize", "tool": "summarizer", "rationale": "Condense the found information."}}
"""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Request: {user_request}"}
        ]
    
    def _parse_plan(self, response: str) -> list[dict]:
        """
        Parses the model's output into a list of step dictionaries.
        
        Args:
            response (str): The raw text response from the model.
            
        Returns:
            list[dict]: The parsed steps.
        """
        steps = []
        try:
            # Look for JSON objects within numbered lists
            pattern = re.compile(r'\d+\.\s*(\{.*?\})', re.DOTALL)
            matches = pattern.findall(response)
            
            for match in matches:
                try:
                    step_data = json.loads(match)
                    steps.append(step_data)
                except json.JSONDecodeError:
                    continue
                    
        except Exception as e:
            logger.error(f"Failed to parse plan from response: {e}")
            
        return steps
