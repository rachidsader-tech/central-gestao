from app import app
import meeting_ai

meeting_ai.register(__import__("app"))
