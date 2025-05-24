import os
import queue
import threading
import time

import pyperclip
import requests
from agents import Agent, function_tool, Runner, WebSearchTool
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from loguru import logger
from playwright.sync_api import sync_playwright

load_dotenv()
JINA_KEY = os.getenv("JINA_KEY")


def search(text: str) -> str:
    for retry in range(3):
        try:
            return DDGS().text(text, safesearch="off", max_results=20, backend="lite")
        except Exception as e:
            time.sleep(retry)
    raise Exception("Failed to search the web (try again later)")


@function_tool(
    name_override="web_search",
    description_override="Search the web and return urls, titles and snippets of the results.",
)
def web_search_tool(text: str) -> str:
    logger.success(f"Searching the web for {text}")
    return search(text)


def read_website(url: str) -> str:
    for retry in range(3):
        url = f"https://r.jina.ai/{url}"
        headers = {"Authorization": f"Bearer {JINA_KEY}"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text
        logger.warning(
            f"Failed to read website {url}: {response.status_code}. Retrying..."
        )
        time.sleep(1)
    raise Exception(f"Failed to read website {url}: {response.status_code}")


@function_tool(
    name_override="read_website",
    description_override="Read the content of a website and return it as a string.",
)
def read_website_tool(url: str) -> str:
    logger.success(f"Reading website {url}")
    assert isinstance(url, str), f"URL must be a string, got {type(url)}"
    result = read_website(url)
    assert isinstance(result, str), f"Result must be a string, got {type(result)}"
    return result


if __name__ == "__main__":
    with open("website.html", "w") as f:
        f.write(
            read_website(
                "https://tvtropes.org/pmwiki/pmwiki.php/Main/BreakingTheFourthWall"
            )
        )
