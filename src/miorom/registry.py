"""
miorom.registry
~~~~~~~~~~~~~~~
Plugin and extensible component registry for MioROM.
Allows developers to hook custom compression algorithms, archive containers,
and game definitions using simple decorators.
"""

from typing import Any, Callable, Dict, Optional, Type


_CODEC_REGISTRY: Dict[str, Any] = {}
_CONTAINER_REGISTRY: Dict[str, Any] = {}
_GAME_REGISTRY: Dict[str, Any] = {}


def register_codec(name: str) -> Callable[[Type[Any]], Type[Any]]:
    """Decorator to register a custom compression codec."""
    def decorator(cls: Type[Any]) -> Type[Any]:
        _CODEC_REGISTRY[name.lower()] = cls
        return cls
    return decorator


def get_codec(name: str) -> Optional[Any]:
    return _CODEC_REGISTRY.get(name.lower())


def list_codecs() -> Dict[str, Any]:
    return dict(_CODEC_REGISTRY)


def register_container(name: str) -> Callable[[Type[Any]], Type[Any]]:
    """Decorator to register a custom archive/container format."""
    def decorator(cls: Type[Any]) -> Type[Any]:
        _CONTAINER_REGISTRY[name.lower()] = cls
        return cls
    return decorator


def get_container(name: str) -> Optional[Any]:
    return _CONTAINER_REGISTRY.get(name.lower())


def list_containers() -> Dict[str, Any]:
    return dict(_CONTAINER_REGISTRY)


def register_game(name: str) -> Callable[[Type[Any]], Type[Any]]:
    """Decorator to register a game definition."""
    def decorator(cls: Type[Any]) -> Type[Any]:
        _GAME_REGISTRY[name.lower()] = cls
        return cls
    return decorator


def get_game(name: str) -> Optional[Any]:
    return _GAME_REGISTRY.get(name.lower())


def list_games() -> Dict[str, Any]:
    return dict(_GAME_REGISTRY)
