from pydantic import BaseModel, Field


class ClarificationRequest(BaseModel):
    message: str = Field(
        description="A friendly, conversational message asking the user for the missing information."
    )
    missing_fields: list[str] = Field(
        description="Machine-readable names of what is missing, e.g. 'destination', 'travel_dates', 'budget'."
    )
