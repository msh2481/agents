import asyncio
import queue
import threading
import time

import pyperclip
from agents import Agent, function_tool, Runner, WebSearchTool
from duckduckgo_search import DDGS
from html2text import HTML2Text
from loguru import logger
from playwright.sync_api import sync_playwright


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


def read_website_raw(url: str) -> str:
    html = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        for _ in range(10):
            time.sleep(0.5)
            current_html = page.content()
            summary = f"len: {len(current_html)} start: {current_html[:20]} end: {current_html[-20:]}"
            check = input(f"Does it look like a website? {summary}\n")
            if check == "y":
                html = current_html
                break
        browser.close()
    if html is not None:
        return html
    while True:
        input("Press Enter when website HTML is copied to clipboard...")
        clipboard_text = pyperclip.paste()
        if len(clipboard_text) > 10:
            break
    logger.success(
        f"Read {len(clipboard_text)} characters from clipboard ({clipboard_text[:20]}...{clipboard_text[-20:]})"
    )


def read_website(url: str) -> str:
    result_queue = queue.Queue()

    def run_in_thread():
        try:
            result = read_website_raw(url)
            result_queue.put(("success", result))
        except Exception as e:
            result_queue.put(("error", e))

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join()

    result_type, result = result_queue.get()
    if result_type == "error":
        raise result
    html = result

    cleaned = HTML2Text().handle(html)
    lines = cleaned.split("\n")
    filtered = [line for line in lines if len(line.strip()) > 10]
    return "\n".join(filtered)


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
