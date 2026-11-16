: "${PYTHON_APP:?Set vars.python_app}"
uv run python -c 'import importlib, os; module, name = os.environ["PYTHON_APP"].split(":", 1); app = getattr(importlib.import_module(module), name); app.openapi(); print("FastAPI import and OpenAPI passed; startup was not checked.")'
