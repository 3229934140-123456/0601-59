import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


DEFAULT_CONFIG = {
    "project_name": "brand-project",
    "image_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff"],
    "font_formats": [".ttf", ".otf", ".woff", ".woff2"],
    "icon_formats": [".svg", ".png", ".ico"],
    "naming_pattern": "{theme}_{name}_{index:03d}",
    "resize_sizes": {
        "icon": [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256), (512, 512)],
        "banner": [(1920, 1080), (1280, 720), (768, 432)],
        "thumbnail": [(400, 300), (200, 150)],
        "square": [(800, 800), (400, 400), (200, 200)],
    },
    "min_resolution": (1024, 768),
    "copyright_text": "",
    "themes": ["default"],
    "palette_colors": 6,
}


@dataclass
class ProjectConfig:
    project_name: str = "brand-project"
    image_formats: List[str] = field(default_factory=lambda: DEFAULT_CONFIG["image_formats"].copy())
    font_formats: List[str] = field(default_factory=lambda: DEFAULT_CONFIG["font_formats"].copy())
    icon_formats: List[str] = field(default_factory=lambda: DEFAULT_CONFIG["icon_formats"].copy())
    naming_pattern: str = DEFAULT_CONFIG["naming_pattern"]
    resize_sizes: Dict[str, List[tuple]] = field(default_factory=lambda: {
        k: [tuple(vv) for vv in v] for k, v in DEFAULT_CONFIG["resize_sizes"].items()
    })
    min_resolution: tuple = field(default_factory=lambda: tuple(DEFAULT_CONFIG["min_resolution"]))
    copyright_text: str = ""
    themes: List[str] = field(default_factory=lambda: ["default"])
    palette_colors: int = 6

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resize_sizes"] = {k: [list(v) for v in vals] for k, vals in self.resize_sizes.items()}
        d["min_resolution"] = list(self.min_resolution)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        cfg = cls()
        for key, value in data.items():
            if hasattr(cfg, key):
                if key == "resize_sizes":
                    setattr(cfg, key, {k: [tuple(vv) for vv in v] for k, v in value.items()})
                elif key == "min_resolution":
                    setattr(cfg, key, tuple(value))
                else:
                    setattr(cfg, key, value)
        return cfg


class ConfigManager:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.config_file = self.project_dir / ".brand-kit" / "config.json"
        self._config: Optional[ProjectConfig] = None

    @property
    def config(self) -> ProjectConfig:
        if self._config is None:
            self.load()
        return self._config

    def load(self) -> ProjectConfig:
        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config = ProjectConfig.from_dict(data)
        else:
            self._config = ProjectConfig()
        return self._config

    def save(self, config: Optional[ProjectConfig] = None):
        if config is not None:
            self._config = config
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)

    def is_initialized(self) -> bool:
        return self.config_file.exists()


def get_project_dir(target_path: Optional[str] = None) -> Path:
    if target_path:
        return Path(target_path).resolve()
    return Path.cwd()


def find_project_root(start_path: Optional[str] = None) -> Optional[Path]:
    current = Path(start_path or os.getcwd()).resolve()
    while True:
        if (current / ".brand-kit" / "config.json").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
