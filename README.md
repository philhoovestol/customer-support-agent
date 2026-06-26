# Customer Support Agent

An agentic refund-processing web application for e-commerce support.

The project is split into:

- `backend/`: FastAPI, LangGraph, SQLite, SQLModel, deterministic refund policy engine.
- `frontend/`: React and Vite customer chat plus admin trace dashboard.
- `docs/`: run instructions and remaining implementation work.

The backend defaults to a deterministic mock LLM so the full product can run
locally without an API key. Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` in
`backend/.env` to use an OpenAI chat model.

See [docs/RUNNING.md](docs/RUNNING.md) for setup steps.

For a visual overview of how the chat agent turns a customer message into a
response, see [docs/CHAT_AGENT_RESPONSE_FLOW.md](docs/CHAT_AGENT_RESPONSE_FLOW.md).

For a public Render Starter deployment, see
[docs/RENDER_DEPLOYMENT.md](docs/RENDER_DEPLOYMENT.md).
