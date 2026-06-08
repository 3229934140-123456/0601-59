import sys
import subprocess
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent


def run_cmd(cmd, stdin=None, cwd=None):
    result = subprocess.run(
        cmd, shell=True, capture_output=True,
        encoding="utf-8", errors="replace",
        input=stdin, cwd=str(cwd) if cwd else None
    )
    return result.returncode, result.stdout + result.stderr


def init_project(name):
    import shutil
    p = BASE_DIR / name
    if p.exists():
        shutil.rmtree(p)
    p.mkdir()
    run_cmd(f"brand-kit init test --path {p}")
    return p


def test_rename_basic():
    project = init_project("test_rename_simple")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "b.png")

    # test: no overwrite + all skip (s)
    import hashlib
    b_before = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b",
        stdin="s\n", cwd=project
    )
    b_after = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    assert b_before == b_after, "b.png should not be modified when skip"
    assert (img_dir / "a.png").exists(), "a.png should still exist"
    print("  [PASS] rename + skip = no change")

    # test: no overwrite + all overwrite (a)
    b_before = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b",
        stdin="a\n", cwd=project
    )
    b_after = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    assert b_before != b_after, "b.png should be modified when overwrite confirmed"
    assert not (img_dir / "a.png").exists(), "a.png should be renamed"
    print("  [PASS] rename + confirm overwrite = file overwritten")

    # test: with overwrite + enter (should skip)
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    b_before = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b --overwrite",
        stdin="\n", cwd=project
    )
    b_after = hashlib.md5((img_dir / "b.png").read_bytes()).hexdigest()
    assert b_before == b_after, "b.png should not change with --overwrite + enter"
    assert (img_dir / "a.png").exists(), "a.png should still exist"
    print("  [PASS] rename + --overwrite + enter = skip (safe)")

    import shutil
    shutil.rmtree(project)


def test_import_basic():
    project = init_project("test_import_simple")
    target = project / "assets/images/default/logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    src_dir = project / "import_src"
    src_dir.mkdir()

    # prepare
    Image.new("RGB", (200, 200), "red").save(target)
    Image.new("RGB", (80, 80), "blue").save(src_dir / "logo.png")

    import hashlib
    target_before = hashlib.md5(target.read_bytes()).hexdigest()

    # test: skip
    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup",
        stdin="s\n", cwd=project
    )
    target_after = hashlib.md5(target.read_bytes()).hexdigest()
    assert target_before == target_after, "target should not change when skip"
    print("  [PASS] import + skip = no change")

    # test: overwrite
    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup",
        stdin="a\n", cwd=project
    )
    target_after = hashlib.md5(target.read_bytes()).hexdigest()
    src_hash = hashlib.md5((src_dir / "logo.png").read_bytes()).hexdigest()
    assert target_after == src_hash, "target should be overwritten"
    print("  [PASS] import + confirm overwrite = file overwritten")

    # test: --overwrite + enter = skip
    Image.new("RGB", (200, 200), "red").save(target)
    target_before = hashlib.md5(target.read_bytes()).hexdigest()
    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup --overwrite",
        stdin="\n", cwd=project
    )
    target_after = hashlib.md5(target.read_bytes()).hexdigest()
    assert target_before == target_after, "target should not change with --overwrite + enter"
    print("  [PASS] import + --overwrite + enter = skip (safe)")

    import shutil
    shutil.rmtree(project)


def test_resize_basic():
    project = init_project("test_resize_simple")
    src = project / "assets/images/photo.png"
    out_dir = project / "output/resized/default"
    out_dir.mkdir(parents=True)

    Image.new("RGB", (200, 200), "green").save(src)
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")

    import hashlib
    thumb_before = hashlib.md5((out_dir / "photo_50x50.png").read_bytes()).hexdigest()

    # test: skip
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default",
        stdin="s\n", cwd=project
    )
    thumb_after = hashlib.md5((out_dir / "photo_50x50.png").read_bytes()).hexdigest()
    assert thumb_before == thumb_after, "thumb should not change when skip"
    print("  [PASS] resize + skip = no change")

    # test: overwrite
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default",
        stdin="a\n", cwd=project
    )
    thumb_after = hashlib.md5((out_dir / "photo_50x50.png").read_bytes()).hexdigest()
    assert thumb_before != thumb_after, "thumb should be regenerated"
    print("  [PASS] resize + confirm overwrite = file regenerated")

    # test: --overwrite + enter = skip
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")
    thumb_before = hashlib.md5((out_dir / "photo_50x50.png").read_bytes()).hexdigest()
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default --overwrite",
        stdin="\n", cwd=project
    )
    thumb_after = hashlib.md5((out_dir / "photo_50x50.png").read_bytes()).hexdigest()
    assert thumb_before == thumb_after, "thumb should not change with --overwrite + enter"
    print("  [PASS] resize + --overwrite + enter = skip (safe)")

    import shutil
    shutil.rmtree(project)


def main():
    print("=== Basic Overwrite Confirm Tests ===")
    print()
    print("rename tests:")
    test_rename_basic()
    print()
    print("import tests:")
    test_import_basic()
    print()
    print("resize tests:")
    test_resize_basic()
    print()
    print("All basic tests passed!")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
