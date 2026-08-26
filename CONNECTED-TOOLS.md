# Connected MCP Servers and Tools

## reddit
Package: `reddit-no-auth-mcp-server` (uvx). No API keys required.

- `reddit_search` — search all of Reddit for a query.
- `reddit_search_subreddit` — search within a specific subreddit.
- `reddit_get_post` — retrieve complete post data, including the comment tree.
- `reddit_get_subreddit_posts` — retrieve a list of posts from a subreddit's feed.
- `reddit_get_user` — retrieve a user's public activity (posts and comments).
- `reddit_get_user_posts` — retrieve posts by a specific user.

## google-trends
Package: `google-trends-mcp` (npx). No keys required.

- `interest_over_time` — weekly interest trend (0–100), for up to five queries at once.
- `compare_terms` — normalized comparison of two to five terms; identifies the leader.
- `related_queries` — top and rising related queries for a topic.
- `trending_now` — current daily trends by country.
- `interest_by_region` — interest broken down by region or country.

## dialog-mcp (reddit-research)
HTTP server: `https://mcp.dialog.tools/mcp`. OAuth2 authentication (Descope) will be initiated automatically on the first call.

Three-layer architecture; use strictly in this order:
1. `discover_operations` — lists available operations and provides workflow recommendations.
2. `get_operation_schema` — retrieves parameters and validation rules before an operation call.
3. `execute_operation` — performs the operation itself (subreddit and post search, saved-feed management, etc.).

Best practice: for a new topic, start with `discover_subreddits`; use the confidence score as a guide (>0.7 — go directly to a specific community, 0.4–0.7 — use several communities, <0.4 — rephrase the query). For two or more subreddits, use `fetch_multiple` to reduce the number of calls. Collect comments from at least 10 posts for a comprehensive analysis. Always include a Reddit link in citations.

---

# Council (skill, not MCP)

The `council` skill is invoked as `/council`. It convenes a council of seven expert AI personas that discuss a decision, idea, or problem from different perspectives, then delivers a structured verdict: confidence in the assessment, critical risks, and concrete next steps.

When to use: requests such as “should I,” “what do you think about,” “help me decide,” or “analyze my idea/strategy/architecture”; requests to stress-test a plan or get different points of view—even when there is no explicit question, if a decision is described that should be examined from several angles.
