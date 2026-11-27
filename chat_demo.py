"""Run the three-turn Kaveri Exports streaming demonstration.

Run with ``python chat_demo.py`` after configuring ``.env`` and the SQLite DB.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

from src.llm_client import Conversation, LLMClient, RunLog, tool_spec

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
LOG_PATH = ROOT / "run_log.jsonl"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'kaveri.db').as_posix()}")
engine = create_engine(DATABASE_URL)


def get_revenue(country: str, year: int) -> str:
    """Return documented order revenue in USD for a country and calendar year.

    The supplied Midstone business brief defines revenue as SUM(orders.total_amount)
    and maps an order's country through its customer. Bind parameters prevent SQL
    interpolation. This function issues one SELECT statement.
    """
    statement = text("""
        SELECT COALESCE(SUM(o.total_amount), 0.00)
        FROM orders AS o
        JOIN customers AS c ON c.customer_id = o.customer_id
        WHERE c.country = :country
          AND o.order_date >= :year_start
          AND o.order_date < :year_end
    """)
    params = {"country": country.strip(), "year_start": f"{int(year):04d}-01-01",
              "year_end": f"{int(year) + 1:04d}-01-01"}
    try:
        with engine.connect() as connection:
            amount = connection.execute(statement, params).scalar_one()
    except SQLAlchemyError as error:
        raise RuntimeError(
            "Could not query revenue. Confirm DATABASE_URL points to the Midstone 2 "
            "SQLite database and that it contains orders and customers tables."
        ) from error
    return f"{float(amount or 0):,.2f}"


TOOLS = [tool_spec(
    "get_revenue",
    "Return actual revenue in USD for a country and calendar year from the sales database.",
    {"country": {"type": "string", "description": "Country name, e.g. Germany"},
     "year": {"type": "integer", "description": "Four-digit year, e.g. 2024"}},
    ["country", "year"],
)]

TURNS = [
    "Hi, what can you do?",
    "What was our revenue from Germany in 2024?",
    "And how does that compare with what I asked first?",
]


def main() -> None:
    """Start a fresh run log and print one streamed conversation with three turns."""
    LOG_PATH.write_text("", encoding="utf-8")
    client = LLMClient(log=RunLog(LOG_PATH))
    conversation = Conversation(
        client,
        system=("You are the Kaveri Exports sales assistant. Be concise. The first user "
                "message is 'Hi, what can you do?' Answer that you can answer company "
                "sales and revenue questions using the database. For every revenue "
                "question, call get_revenue; never guess numbers. When reporting a tool "
                "result, copy the numeric string from the tool exactly; do not recalculate "
                "or change its digits. The third user message asks how the Germany 2024 "
                "revenue question compares with the first user message. The first message "
                "was about your capabilities, not a revenue period or amount. Say that "
                "they are different topics and cannot be numerically compared. Do not "
                "invent a different first question and do not repeat the revenue amount "
                "as a comparison."),
        tools=TOOLS,
        functions={"get_revenue": get_revenue},
        conversation_id="c1",
    )
    for turn_index, question in enumerate(TURNS):
        if turn_index == 2:
            conversation.history.append({
                "role": "system",
                "content": (
                    "Conversation reminder for this turn: User turn 1 was exactly "
                    "'Hi, what can you do?' and asked about assistant capabilities. User "
                    "turn 2 asked for Germany revenue in 2024. The phrase 'what I asked "
                    "first' refers to user turn 1, not turn 2. Explain that the first "
                    "question was about capabilities and the current topic is Germany "
                    "revenue, so there is no numeric comparison. Do not claim the first "
                    "question asked about revenue."
                ),
            })
        print(f"\nYOU: {question}\nAI:  ", end="", flush=True)
        conversation.ask(question, on_token=lambda piece: print(piece, end="", flush=True))
        print()
    print(f"\nWrote {LOG_PATH}")


if __name__ == "__main__":
    main()
