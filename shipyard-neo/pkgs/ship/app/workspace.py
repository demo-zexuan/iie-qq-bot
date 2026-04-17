"""
Workspace management utilities for file system operations.

This module provides utilities for managing the fixed workspace directory,
ensuring security by preventing access outside the designated workspace.
"""

from pathlib import Path
from fastapi import HTTPException

# 固定的 workspace 根目录
WORKSPACE_ROOT = Path("/workspace")


def get_workspace_dir() -> Path:
    """
    获取 workspace 目录路径

    Returns:
        Path: workspace 目录路径
    """
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_ROOT


def resolve_path(path: str) -> Path:
    """
    安全的路径解析

    Args:
        path: 要解析的路径

    Returns:
        Path: 解析后的绝对路径

    Raises:
        HTTPException: 当路径在 workspace 外时抛出 403 错误
    """
    workspace_dir = get_workspace_dir().resolve()
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = workspace_dir / candidate

    candidate = candidate.resolve()
    try:
        candidate.relative_to(workspace_dir)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: path must be within workspace {workspace_dir}",
        )

    return candidate
