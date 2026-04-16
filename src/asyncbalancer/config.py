# your_package/config.py
import json
import tomllib
import os
from pathlib import Path
from typing import Optional, Any, Dict
from dotenv import load_dotenv, find_dotenv

class Config:
    def __init__(
        self, 
        config_file: Optional[str] = None,
        env_file: Optional[str] = None,
        toml_section: str = "tool.asyncbalancer"
    ):
        self._config: Dict[str, Any] = {}
        self.toml_section = toml_section
        
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv(find_dotenv(usecwd=True))
        
        toml_path = self._find_config_file(config_file)
        if toml_path and toml_path.exists():
            with open(toml_path, "rb") as f:
                full_config = tomllib.load(f)
                self._config = self._get_nested_section(full_config, toml_section)
        
        self._merge_env_into_config()
        self._merge_resources_from_external_file()

    def add(self, key: str, value: Any) -> None:
        self._config[key] = value
    
    def _find_config_file(self, config_file: Optional[str]) -> Optional[Path]:
        """Szuka config.toml lub pyproject.toml"""
        if config_file:
            return Path(config_file)
        
        cwd = Path.cwd()
        
        for filename in ["config.toml", "pyproject.toml"]:
            config_path = cwd / filename
            if config_path.exists():
                return config_path
            
            current = cwd.parent
            while current != current.parent:
                config_path = current / filename
                if config_path.exists():
                    return config_path
                current = current.parent
        
        return None
    
    def _get_nested_section(self, config: dict, section_path: str) -> dict:
        sections = section_path.split('.')
        result = config
        
        for section in sections:
            if isinstance(result, dict) and section in result:
                result = result[section]
            else:
                return {}
        
        return result if isinstance(result, dict) else {}

    def _merge_env_into_config(self) -> None:
        prefix = "ASYNCBALANCER_"
        for env_key, raw_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue

            suffix = env_key[len(prefix):]
            if not suffix:
                continue

            path_parts = [part.lower() for part in suffix.split('_') if part]
            if not path_parts:
                continue

            self._set_nested_value(path_parts, self._parse_value(raw_value))

    def _set_nested_value(self, path_parts: list[str], value: Any) -> None:
        current = self._config

        for part in path_parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, dict):
                current[part] = {}
            current = current[part]

        current[path_parts[-1]] = value

    def _merge_resources_from_external_file(self) -> None:
        driver_name = self._config.get("driver")
        driver_resources_file = None
        if driver_name:
            drivers = self._config.get("drivers") or {}
            if isinstance(drivers, dict):
                driver_config = drivers.get(driver_name) or {}
                if isinstance(driver_config, dict):
                    driver_resources_file = driver_config.get("resources_file")

        resources_file = (
            os.getenv("ASYNCBALANCER_RESOURCES_FILE")
            or self._config.get("resources_file")
            or driver_resources_file
        )
        if not resources_file:
            return

        file_path = Path(resources_file).expanduser()
        if not file_path.exists():
            return

        external_data: Dict[str, Any]
        if file_path.suffix.lower() == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                external_data = json.load(f)
        else:
            with open(file_path, "rb") as f:
                external_data = tomllib.load(f)

        self._apply_external_resources(external_data)

    def _apply_external_resources(self, external_data: Dict[str, Any]) -> None:
        providers_resources: Dict[str, Any] = {}

        # Format A:
        # {"providers": {"gemini": {"resources": [...]}, "claude": {"resources": [...]}}}
        providers_block = external_data.get("providers")
        if isinstance(providers_block, dict):
            for provider_name, provider_config in providers_block.items():
                if isinstance(provider_config, dict) and isinstance(provider_config.get("resources"), list):
                    providers_resources[provider_name] = provider_config["resources"]

        # Format B:
        # {"gemini": [...], "claude": [...]}
        if not providers_resources:
            for provider_name, resources in external_data.items():
                if isinstance(resources, list):
                    providers_resources[provider_name] = resources

        if not providers_resources:
            return

        providers_config = self._config.setdefault("providers", {})
        for provider_name, resources in providers_resources.items():
            provider_config = providers_config.setdefault(provider_name, {})
            provider_config["resources"] = resources
    
    def get(self, key: str, default: Any = None) -> Any:
        env_key = f"ASYNCBALANCER_{key.upper().replace('.', '_')}"
        env_value = os.getenv(env_key)
        
        if env_value is not None:
            return self._parse_value(env_value)
        
        # Sprawdź w TOML (obsługa nested keys)
        value = self._config
        for part in key.split('.'):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return default
        
        return value if value is not None else default
    
    def _parse_value(self, value: str) -> Any:
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        try:
            return int(value)
        except ValueError:
            pass
        
        try:
            return float(value)
        except ValueError:
            pass
        
        return value
    
    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key, default)
        return int(value) if value is not None else default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return default
    
    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return str(value) if value is not None else default

_default_config: Optional[Config] = None

def get_config() -> Config:
    global _default_config
    if _default_config is None:
        _default_config = Config()
    return _default_config

def configure(
    config_file: Optional[str] = None,
    env_file: Optional[str] = None,
    toml_section: str = "tool.asyncbalancer"
) -> Config:
    global _default_config
    _default_config = Config(config_file, env_file, toml_section)
    return _default_config