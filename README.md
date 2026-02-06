# Voltsnip

A searchable code snippet repository with semantic search, built for developers and AI agents who want to reuse proven solutions instead of reinventing them.

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org) [![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688.svg)](https://fastapi.tiangolo.com) [![MCP Ready](https://img.shields.io/badge/MCP-Ready-purple.svg)](https://modelcontextprotocol.io) [![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Explore](https://voltsnip.thetechcruise.com) · [API Docs](https://voltsnip-api.thetechcruise.com/docs) · [Report Bug](https://github.com/vaddisrinivas/voltsnip/issues)

---

> **⚠️ Development Status**  
> This is a personal project in active development. All data sent to the public API is **public and unencrypted**. Do not use it for production workloads or sensitive code.

## What It Does

Voltsnip stores code snippets with semantic search capabilities. Instead of rewriting common utilities or asking an LLM to generate the same pattern repeatedly, you can search for existing implementations that have been tested and refined by others.

**Core features:**
- **Semantic search** – Find snippets by describing what you need, not just keyword matching
- **Community ratings** – Vote on snippets to surface the most useful solutions
- **Multi-language support** – Store and search across Python, JavaScript, Go, and more
- **MCP integration** – Native support for AI agents via Model Context Protocol
- **HTTP API** – Use it from any tool or workflow

## Why Use This

**For developers:**
- Quickly find working implementations of common patterns (retry logic, data validation, parsing utilities)
- Build a personal or team knowledge base of proven solutions
- Reduce time spent searching Stack Overflow or reading documentation

**For AI agents:**
- Retrieve tested code instead of generating potentially flawed solutions from scratch
- Save tokens by injecting compact, working snippets into context
- Enable knowledge sharing between agent sessions or across a team

Research like the [PAL (Program-aided Language Models)](https://arxiv.org/abs/2211.10435) paper shows that LLMs perform better when they can reference working code. Voltsnip provides a practical memory layer for this approach.

## Getting Started

### Hosted API (Recommended)

- API documentation: https://voltsnip-api.thetechcruise.com/docs
- MCP endpoint: https://voltsnip-api.thetechcruise.com/mcp

### Run with Docker Compose (Self-Hosted)

1. **Clone and configure**
```bash
git clone https://github.com/vaddisrinivas/voltsnip.git
cd voltsnip/backend
cp .env.example .env
```

2. **Edit `.env`** with your settings. For local Docker usage:
```
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/voltsnip
```

3. **Start services**
```bash
docker compose up --build
```

4. **Run database migrations**
```bash
docker compose exec backend alembic upgrade head
```

5. **Access the application**
- API documentation: http://localhost:8000/docs
- MCP endpoint: http://localhost:8000/mcp

### Run Locally with uv

```bash
cd backend
cp .env.example .env
# Edit .env with your database settings

uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Use with AI Agents

#### Quick Start: Install as a Skill
```bash
npx skills add vaddisrinivas/voltsnip/voltsnip-skill
```
This is the install path that drives skills.sh listing. See `docs/skills-sh-listing.md` for details.

#### Optional: Fetch SKILL.md via npm
```bash
npx @vaddisrinivas/voltsnip-skill --output ./SKILL.md
```
This is a convenience for local copy only (it does not affect skills.sh ranking).

#### Claude Desktop Integration (Hosted MCP)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "voltsnip": {
      "url": "https://voltsnip-api.thetechcruise.com/mcp",
      "transport": "http"
    }
  }
}
```
If your client expects SSE, set `"transport": "sse"` with the same URL.

#### VS Code (Cline/Cursor) (Hosted MCP)

Add to your MCP settings file (typically `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/mcpSettings.json`):
```json
{
  "voltsnip": {
    "url": "https://voltsnip-api.thetechcruise.com/mcp",
    "transport": "http"
  }
}
```

See [voltsnip-skill/README.md](voltsnip-skill/README.md) for detailed integration guides.

## How It Works

**Stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0
- Database: PostgreSQL 16 with pgvector for semantic search
- Embeddings: fastembed (runs locally, no external API calls)
- Interfaces: RESTful HTTP API + MCP server

**Search flow:**
1. Query is converted to an embedding vector using fastembed
2. PostgreSQL's pgvector extension finds semantically similar snippets
3. Results are ranked by a combination of similarity score, votes, and usage
4. Snippets include metadata (language, tags, author) for context

## Use Cases

**Common development tasks:**
- Need a retry decorator with exponential backoff? Search "retry exponential backoff"
- Parsing structured data from text? Find regex patterns others have refined
- Setting up a common config pattern? Retrieve a template someone's already debugged

**Agent workflows:**
- Agent encounters a known problem and searches for a proven solution
- Agent creates a working implementation and saves it for future reuse
- Different agents (or runs) share knowledge without requiring conversation history

## Roadmap

**Near-term improvements:**
- Automated secret detection to prevent credential leaks
- Code quality checks on submission (linting, basic static analysis)
- Better snippet versioning and forking

**Future exploration:**
- Private team instances or namespaces
- CLI tool for terminal-based search and submission
- Editor plugins (VS Code, JetBrains)
- GitHub integration for importing from gists or repos

## Contributing

This is a personal project, but contributions are welcome:
- Bug fixes and performance improvements
- Better search relevance or ranking algorithms
- Documentation improvements
- New integrations or tooling

Please keep PRs focused and avoid submitting proprietary or sensitive code to the public instance.

## Repository Structure

```
voltsnip/
├── backend/          # FastAPI application and MCP server
├── frontend/         # Web interface (HTML/CSS/JS)
├── voltsnip-skill/   # MCP skill documentation and references
├── scripts/          # Build/deploy scripts
└── local_storage/    # Local dev storage (optional)
```

## License

MIT License - see [LICENSE](LICENSE) for details.

---

**Connect:** [LinkedIn](https://www.linkedin.com/in/srinivasvaddi)  
**Note:** Significant portions of this project were developed with assistance from AI coding tools.
