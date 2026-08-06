"""Pydantic models for tool inputs and outputs."""

from pydantic import BaseModel, Field


class CypherGeneratorInput(BaseModel):
    """Input for cypher_generator tool."""

    user_query: str = Field(description="The user's natural language question")
    db_schema: str = Field(description="Graph database schema description")
    conversation_history: list[str] = Field(
        default_factory=list, description="Recent conversation turns for context"
    )


class CypherGeneratorOutput(BaseModel):
    """Output from cypher_generator tool."""

    cypher_query: str = Field(description="The generated Cypher query")
    reasoning: str = Field(default="", description="Brief explanation of the generated query")


class DbExecutorInput(BaseModel):
    """Input for db_executor tool."""

    cypher_query: str = Field(description="Cypher query to execute")


class DbExecutorOutput(BaseModel):
    """Output from db_executor tool."""

    success: bool
    data: list[dict] | None = None
    error: str | None = None


class InterpreterInput(BaseModel):
    """Input for result_interpreter tool."""

    db_result: list[dict] = Field(description="Raw query results from database")
    user_query: str = Field(description="The original user question")


class InterpreterOutput(BaseModel):
    """Output from result_interpreter tool."""

    answer: str = Field(description="Natural language answer")
