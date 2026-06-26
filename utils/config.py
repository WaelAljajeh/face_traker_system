import os
import yaml
from typing import Dict, Any


def get_appdata_dir(subdir: str = "face_attendance") -> str:
    """Get a per-user data directory (APPDATA on Windows, ~/.local/share on others)."""
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_DATA_HOME', os.path.join(os.path.expanduser('~'), '.local', 'share'))
    data_dir = os.path.join(base, subdir)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


class Config:
    """YAML configuration loader and accessor."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = {}
        return cls._instance
    
    @classmethod
    def load(cls, config_path: str) -> 'Config':
        """Load YAML config file."""
        instance = cls()
        with open(config_path, 'r') as f:
            instance._config = yaml.safe_load(f)
        return instance
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        Get config value by dot-notation path.
        
        Example: config.get("insightface.model_name")
        """
        keys = path.split('.')
        value = self._config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire config section."""
        return self._config.get(section, {})
    
    def __repr__(self):
        return f"Config({self._config})"
