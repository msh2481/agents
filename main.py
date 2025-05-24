import logging
from datetime import datetime
from pprint import pprint

from agents import Agent, handoff, trace, Trace, WebSearchTool
from loguru import logger


# Intercept 'openai.agents' logs and route them to loguru
class LoguruHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info, depth=6).log(level, record.getMessage())


logging.getLogger("openai.agents").addHandler(LoguruHandler())
logging.getLogger("openai.agents").setLevel(logging.DEBUG)
logger.remove()
logger.add(f"logs/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log", level="DEBUG")


researcher = Agent(
    name="Researcher",
    instructions=(
        "You are a researcher known for your ability to find anything on the internet, "
        "as well as your critical thinking and ability to extract exactly the information other agents need for their tasks."
    ),
    tools=[WebSearchTool()],
    model="gpt-4.1-mini",
)

researcher_tool = researcher.as_tool(
    tool_name="Researcher",
    tool_description="A helpful agent that finds the requested information on the internet.",
)

researcher_handoff = handoff(
    agent=researcher,
    tool_description_override="A helpful agent that finds the requested information on the internet.",
)

supervisor = Agent(
    name="Supervisor",
    instructions=(
        "You are the guy who gets things done. "
        "Your responsibility is to oversee that the project is going in the right direction "
        "and give the tasks to the competent agents. "
        "You don't actually do the tasks yourself."
    ),
    tools=[researcher_tool],
    model="o4-mini",
)

if __name__ == "__main__":
    from agents.run import Runner

    result = Runner.run_sync(
        starting_agent=supervisor,
        input="Find the latest news about the stock market.",
    )
    print(result.final_output)
