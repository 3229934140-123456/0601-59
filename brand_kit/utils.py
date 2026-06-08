import os
import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple, Set
from send2trash import send2trash


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".tif"}
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".eot"}
ICON_EXTENSIONS = {".svg", ".png", ".ico", ".icns"}


def get_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def get_files_by_extension(directory: Path, extensions: Set[str],
                           recursive: bool = True) -> List[Path]:
    files = []
    if recursive:
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                filepath = Path(root) / filename
                if filepath.suffix.lower() in extensions:
                    files.append(filepath)
    else:
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in extensions:
                files.append(item)
    return sorted(files)


def get_file_category(file_path: Path) -> Optional[str]:
    ext = file_path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in FONT_EXTENSIONS:
        return "font"
    if ext in ICON_EXTENSIONS:
        return "icon"
    return None


def safe_move(source: Path, target: Path, overwrite: bool = False) -> Tuple[bool, str]:
    if not source.exists():
        return False, f"源文件不存在: {source}"
    if target.exists():
        if not overwrite:
            return False, f"目标文件已存在: {target}"
        try:
            send2trash(str(target))
        except Exception:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(str(source), str(target))
        return True, f"移动成功: {source} -> {target}"
    except OSError:
        import shutil
        shutil.copy2(str(source), str(target))
        send2trash(str(source))
        return True, f"复制并删除成功: {source} -> {target}"


def safe_copy(source: Path, target: Path, overwrite: bool = False) -> Tuple[bool, str]:
    import shutil
    if not source.exists():
        return False, f"源文件不存在: {source}"
    if target.exists():
        if not overwrite:
            return False, f"目标文件已存在: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    return True, f"复制成功: {source} -> {target}"


def sanitize_filename(name: str) -> str:
    invalid_chars = r'[\\/:*?"<>|]'
    name = re.sub(invalid_chars, "_", name)
    name = name.strip().strip(".")
    if not name:
        name = "unnamed"
    return name


def get_next_available_path(target_dir: Path, filename: str) -> Path:
    target = target_dir / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        target = target_dir / new_name
        if not target.exists():
            return target
        counter += 1


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def human_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}分{secs:.1f}秒"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}小时{minutes}分{secs:.1f}秒"


def confirm_overwrite(files_to_overwrite: List[Tuple[Path, Path]],
                      auto_confirm: bool = False) -> List[Tuple[Path, Path]]:
    if auto_confirm:
        return files_to_overwrite

    if not files_to_overwrite:
        return []

    import click

    click.echo(click.style(
        f"\n⚠  以下 {len(files_to_overwrite)} 个文件将被覆盖:",
        fg="yellow", bold=True
    ))

    for i, (source, target) in enumerate(files_to_overwrite[:10], 1):
        click.echo(f"  {i:2d}. {target.name}")

    if len(files_to_overwrite) > 10:
        click.echo(f"  ... 还有 {len(files_to_overwrite) - 10} 个文件")

    if not click.confirm("\n是否确认覆盖这些文件?", default=False):
        click.echo(click.style("已跳过所有将被覆盖的文件", fg="cyan"))
        return []

    return files_to_overwrite


def check_overwrites(source_target_pairs: List[Tuple[Path, Path]]) -> List[Tuple[Path, Path]]:
    return [(s, t) for s, t in source_target_pairs if t.exists()]


def get_icon_extensions() -> set:
    return {".ico", ".icns"}


def is_icon_file(file_path: Path, base_dir: Path = None) -> bool:
    ext = file_path.suffix.lower()
    if ext in get_icon_extensions():
        return True
    if base_dir is not None:
        try:
            rel = file_path.relative_to(base_dir)
            if "icons" in rel.parts or "icon" in rel.parts:
                return True
        except ValueError:
            pass
    return False


def is_image_file(file_path: Path, base_dir: Path = None) -> bool:
    ext = file_path.suffix.lower()
    if ext in IMAGE_EXTENSIONS and ext not in get_icon_extensions():
        if base_dir is not None:
            try:
                rel = file_path.relative_to(base_dir)
                if "icons" in rel.parts or "icon" in rel.parts:
                    return False
            except ValueError:
                pass
        return True
    return False


def is_font_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in FONT_EXTENSIONS
