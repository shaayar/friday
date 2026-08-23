"""
System tools — time, environment info, shell commands, etc.
"""

import ast
import datetime
import platform


# Safe evaluation of mathematical expressions
class SafeEvaluator(ast.NodeVisitor):
    """Safely evaluate mathematical expressions using AST."""

    ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
        {
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Num,
            ast.Constant,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.FloorDiv,
            ast.Mod,
            ast.Pow,
            ast.USub,
            ast.UAdd,
        }
    )

    def visit(self, node):
        if type(node) not in self.ALLOWED_NODES:
            raise ValueError(f"Operation not allowed: {type(node).__name__}")
        return super().visit(node)


def safe_eval(expression: str) -> float:
    """Safely evaluate a mathematical expression."""
    tree = ast.parse(expression, mode="eval")
    SafeEvaluator().visit(tree)
    return eval(compile(tree, "<string>", "eval"), {"__builtins__": {}}, {})


def register(mcp):

    @mcp.tool()
    def get_current_time() -> str:
        """Return the current date and time in ISO 8601 format."""
        return datetime.datetime.now(datetime.UTC).isoformat()

    @mcp.tool()
    def get_system_info() -> dict:
        """Return basic information about the host system."""
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        }

    @mcp.tool()
    def calculate(expression: str) -> dict:
        """
        Safely evaluate a mathematical expression.
        Supports: +, -, *, /, //, %, **, and parentheses.
        Example: calculate("2 + 3 * 4") returns 14
        """
        try:
            result = safe_eval(expression)
            return {"expression": expression, "result": result, "success": True}
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
            return {"expression": expression, "error": str(e), "success": False}
