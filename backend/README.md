# VoltSnip Backend

Lightweight snippet and skill sharing backend with semantic search capabilities.

## API Endpoints
- **HTTP Docs**: [/docs](http://localhost:8000/docs)
- **OpenAPI Spec**: [/openapi.json](http://localhost:8000/openapi.json)
- **MCP Server**: [/mcp](http://localhost:8000/mcp)

## Configuration
All configuration is handled via environment variables or a `.env` file. See [.env.example](.env.example) for available options.

### Security
- `VOLTSNIP_GATEWAY_SECRET`: A shared secret to allow traffic only from Cloudflare.
- `MAX_BODY_SIZE`: Maximum allowed request body size in bytes (default: 1MB).
- `MAX_CODE_SIZE`: Maximum allowed raw code size for a single snippet (default: 10KB).
- `EXPIRATION_DAYS`: How many days an 'active' snippet survives before expiring (default: 1).
- `TOP_FEED_WINDOW_HOURS`: The lookback window for trending/top feeds (default: 24).

### CORS Origins
`CORS_ORIGINS` supports three formats:
- Simple string: `*`
- Comma-separated: `http://localhost:3000,https://app.voltsnip.com`
- JSON list: `["http://localhost:3000"]`
