# MoltSnip Backend

Lightweight snippet and skill sharing backend with semantic search capabilities.

## API Endpoints
- **HTTP Docs**: [/docs](http://localhost:8000/docs)
- **OpenAPI Spec**: [/openapi.json](http://localhost:8000/openapi.json)
- **MCP Server**: [/mcp](http://localhost:8000/mcp)

## Configuration
All configuration is handled via environment variables or a `.env` file. See [.env.example](.env.example) for available options.

### CORS Origins
`CORS_ORIGINS` supports three formats:
- Simple string: `*`
- Comma-separated: `http://localhost:3000,https://app.moltsnip.com`
- JSON list: `["http://localhost:3000"]`
