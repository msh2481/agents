import asyncio
import time

import pyperclip
from agents import Agent, function_tool, Runner, WebSearchTool
from duckduckgo_search import DDGS
from html2text import HTML2Text
from loguru import logger
from playwright.async_api import async_playwright


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
    while True:
        input("Press Enter when website HTML is copied to clipboard...")
        clipboard_text = pyperclip.paste()
        if len(clipboard_text) > 10:
            break
    logger.success(
        f"Read {len(clipboard_text)} characters from clipboard ({clipboard_text[:20]}...{clipboard_text[-20:]})"
    )

    # async with async_playwright() as p:
    #     browser = await p.chromium.launch(headless=True)
    #     page = await browser.new_page()
    #     await page.goto(url)
    #     await asyncio.sleep(2)
    #     html = await page.content()
    #     await browser.close()
    #     return html


def read_website(url: str) -> str:
    html = read_website_raw(url)
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
    return read_website(url)


if __name__ == "__main__":
    with open("website.html", "w") as f:
        f.write(
            read_website(
                "https://platform.openai.com/docs/guides/images-vision?api-mode=responses"
            )
        )
