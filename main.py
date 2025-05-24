import logging
import sys
from datetime import datetime
from pprint import pprint
from typing import Any

from agents import Agent, function_tool, Runner, Tool, WebSearchTool
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


def get_user_plan_approval(plan: str) -> dict[str, Any]:
    """Shows plan to user and gets their approval with optional suggestions."""
    print("\n" + "=" * 60)
    print("PROPOSED PLAN:")
    print("=" * 60)
    print(plan)
    print("=" * 60)

    response = input(
        "\nApprove this plan? (y/Y to approve, or describe changes needed): "
    ).strip()

    if response.lower() == "y":
        return {"approval": True, "suggestions": ""}
    else:
        return {"approval": False, "suggestions": response}


@function_tool(
    name_override="get_user_plan_approval",
    description_override="Shows a plan to the user and gets their approval with optional suggestions for changes.",
)
def get_user_plan_approval_tool(plan: str) -> dict[str, Any]:
    return get_user_plan_approval(plan)


def plan_and_solve(task: str, tools: list[Tool]) -> bool:
    """Creates a plan, gets user approval, then executes it with iterative feedback."""

    user_feedback = ""
    while True:
        # Phase 1: Plan creation and approval
        planner = Agent(
            name="Planner",
            instructions=(
                "Your job is to create a high-level plan for the given task. "
                "DON'T write any code yet."
                "Break down the task into clear, actionable steps. "
                "Be specific about what needs to be done, but don't actually do it yet. "
                "Output your plan as a numbered list with clear descriptions of each step."
            ),
            model="gpt-4.1",
        )

        plan_approved = False
        while not plan_approved:
            print(f"\n🤔 Creating plan for task: {task}")
            plan_result = Runner.run_sync(
                starting_agent=planner,
                input=f"Create a plan for this task: {task}\n\nHere is the user feedback from the previous iteration: {user_feedback}",
            )

            approval_result = get_user_plan_approval(plan_result.final_output)
            if approval_result["approval"]:
                plan_approved = True
                approved_plan = plan_result.final_output
            else:
                logger.debug(
                    f"\n📝 Plan needs revision: {approval_result['suggestions']}"
                )
                planner.instructions += f"\n\nYour previous plan was:\n{plan_result.final_output}\n\nThe user provided this feedback on your previous plan: {approval_result['suggestions']}\nPlease revise the plan accordingly."

        print(f"\n✅ Plan approved! Proceeding with execution...")

        # Phase 2: Plan execution
        executor = Agent(
            name="Executor",
            instructions=(
                f"Here is the task:\n{task}\n\n"
                f"Here is the approved plan:\n\n{approved_plan}\n\n"
                "Complete the task using the tools provided, according to the plan."
                "Be methodical and thorough. When you're done, provide a summary of what was accomplished."
            ),
            tools=tools,
            model="gpt-4.1",
        )

        execution_result = Runner.run_sync(
            starting_agent=executor,
            input=f"Execute the approved plan for: {task}",
            max_turns=100,
        )

        # Phase 3: User verification and fixes
        print("\n" + "=" * 60)
        print("EXECUTION COMPLETED:")
        print("=" * 60)
        print(execution_result.final_output)
        print("=" * 60)

        user_feedback = input(
            "\nIs the task completed satisfactorily? (y/Y if yes, or describe what needs to be fixed): "
        ).strip()

        if user_feedback.lower() == "y":
            return True
        else:
            logger.debug(f"\n🔧 Making adjustments based on feedback: {user_feedback}")
            continue


if __name__ == "__main__":
    from agents.run import Runner

    result = Runner.run_sync(
        starting_agent=researcher,
        input="find me the paper where they show that surge in Russian wages in 2022-2023 is explained as post-COVID recovery. the authors are from Higher School of Economics",
        max_turns=1000,
    )
    print(result.final_output)
