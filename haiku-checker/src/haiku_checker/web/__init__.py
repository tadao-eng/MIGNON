"""自前ホスト用の Web アプリ（FastAPI）。"""

from __future__ import annotations


def create_app():
    """遅延 import。FastAPI 未インストールでも CLI 本体は動く。"""
    from .app import create_app as _create_app

    return _create_app()


__all__ = ["create_app"]
