from langchain_tavily import TavilySearch

from trip_planner.config import get_settings

_MAX_RESULTS = 5


def build_web_search_tool() -> TavilySearch:
    """Create a Tavily web search tool limited to the top N results."""
    settings = get_settings()
    return TavilySearch(max_results=_MAX_RESULTS, tavily_api_key=settings.tavily_api_key)


web_search_tool = build_web_search_tool()
