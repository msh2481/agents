import logging
import sys
from datetime import datetime
from pprint import pprint

from agents import Agent, function_tool, WebSearchTool
from loguru import logger
from websearch import read_website_tool, web_search_tool


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
logger.add(sys.stdout, level="SUCCESS")

search_reviewer = Agent(
    name="Search Reviewer",
    instructions=(
        "You will be given a search request and the results of the search.\n"
        "Your responsibility is to review the results and determine if they are satisfactory.\n"
        "Be critical and objective: if the search request had several 'AND' conditions, make sure that all of them are satisfied.\n"
        "Provide your verdict in the output: whether the search was successful, and if not, why.\n"
    ),
    model="gpt-4.1-mini",
)

verify_search_results_tool = search_reviewer.as_tool(
    tool_name="verify_search_results",
    tool_description=(
        "Carefully checks whether the search results satisfy the original request.\n"
        "Input format is\n'request: <request text>\nresults: <results text>'\n"
    ),
)


@function_tool(
    name_override="verify_plan",
    description_override=("Evaluates whether the plan makes sense and is effective.\n"),
)
def verify_plan(plan: str) -> bool:
    logger.success(f"Plan: {plan}")
    return True


researcher = Agent(
    name="Researcher",
    instructions=(
        "You will be given a search request and your responsibility is to find the required information on the internet.\n"
        "1. Identify the ways to approach this search. Of course, just calling web search with the request text is always an option, but often that will not be enough. Be creative and strategic. Check your plan with `verify_plan` tool.\n"
        "2. Run the searches you planned using `web_search` tool, and analyze whether you found the information you were looking for.\n"
        "3. If some items seem relevant, use `read_website` tool to read the full content of those pages. Again, check whether that's what you were looking for. \n"
        "3. If the results are not satisfactory, go to step 1 again. Repeat until success (though not more than 10 times).\n"
        "4. Give a detailed summary of the results you found. Quote the relevant parts, give links to the sources. Don't rely on your general knowledge to provide the answers. Everything you return as output should be based on the outputs of 'web_search' tool.\n"
        "5. Check the results with `verify_search_results` tool. If it doesn't find the results satisfactory, reflect on your mistakes and go to step 1 again. Otherwise, the task is done.\n"
    ),
    tools=[
        verify_plan,
        web_search_tool,
        read_website_tool,
        verify_search_results_tool,
    ],
    model="gpt-4.1",
)

researcher_tool = researcher.as_tool(
    tool_name="internet_search_agent",
    tool_description=(
        "Give him a precise task and he will find the information on the internet.\n"
        "Input format should NOT be like a Google query, but instead as a task you would give to a human assistant for research.\n"
        "Make sure to ask for some proofs, or double-check the information in other ways, because he is not always reliable.\n"
        "In general, make your request as clear and detailed as possible, to ensure that the agent knows exactly what to search for.\n"
    ),
)


supervisor = Agent(
    name="Supervisor",
    instructions=(
        "You are the guy who gets things done. "
        "Your responsibility is to oversee that the project is going in the right direction.\n"
        "and give the tasks to the competent agents.\n"
        "You don't actually do the tasks yourself.\n"
        "IMPORTANT: Before taking any action (such as delegating a task), think on what is your current strategy and what action will actually be optimal.\n"
    ),
    tools=[researcher_tool],
    model="o4-mini",
)

if __name__ == "__main__":
    from agents.run import Runner

    result = Runner.run_sync(
        starting_agent=researcher,
        input="find me the paper where they show that surge in Russian wages in 2022-2023 is explained as post-COVID recovery. the authors are from Higher School of Economics",
        max_turns=1000,
    )
    print(result.final_output)
