import sys
import subprocess
import shutil
import hashlib
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
    p = BASE_DIR / name
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    run_cmd(f'brand-kit init test --path "{p}"')
    return p


def md5(file_path):
    return hashlib.md5(Path(file_path).read_bytes()).hexdigest()


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, msg=""):
        self.failed += 1
        print(f"  [FAIL] {name}")
        if msg:
            print(f"         {msg}")

    def summary(self):
        print()
        print("=" * 50)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print("=" * 50)
        return self.failed == 0


def test_rename_overwrite_all_skip(r):
    """rename: 不带 --overwrite，选全部跳过"""
    project = init_project("t_rename_skip")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "b.png")

    b_before = md5(img_dir / "b.png")
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b",
        stdin="s\n", cwd=project
    )

    assert b_before == md5(img_dir / "b.png"), "b.png should not change"
    assert (img_dir / "a.png").exists(), "a.png should exist"
    assert "跳过" in out and "新增" in out, "summary should show 跳过 and 新增"
    r.ok("rename + all skip = no change, summary correct")


def test_rename_overwrite_all_yes(r):
    """rename: 不带 --overwrite，选全部覆盖"""
    project = init_project("t_rename_yes")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "b.png")

    b_before = md5(img_dir / "b.png")
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b",
        stdin="a\n", cwd=project
    )

    assert b_before != md5(img_dir / "b.png"), "b.png should be overwritten"
    assert not (img_dir / "a.png").exists(), "a.png should be renamed away"
    assert "覆盖" in out and "新增" in out, "summary should show 覆盖 and 新增"
    r.ok("rename + all overwrite = file overwritten, summary correct")


def test_rename_overwrite_each(r):
    """rename: 逐个确认模式（验证确认界面存在，逐个确认可用）"""
    project = init_project("t_rename_each")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "b.png")

    b_before = md5(img_dir / "b.png")
    a_exists_before = (img_dir / "a.png").exists()

    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b",
        stdin="i\ny\n", cwd=project
    )

    assert "逐个确认" in out, "should show interactive mode option"
    r.ok("rename + interactive mode = option available")


def test_import_overwrite_each(r):
    """import: 逐个确认模式，y 覆盖、n 跳过、回车跳过"""
    project = init_project("t_import_each")
    t_dir = project / "assets/images/default"
    t_dir.mkdir(parents=True, exist_ok=True)
    s_dir = project / "import_src"
    s_dir.mkdir()

    Image.new("RGB", (100, 100), "red").save(t_dir / "img1.png")
    Image.new("RGB", (50, 50), "blue").save(t_dir / "img2.jpg")
    Image.new("RGB", (30, 30), "green").save(t_dir / "img3.png")
    Image.new("RGB", (10, 10), "yellow").save(s_dir / "img1.png")
    Image.new("RGB", (10, 10), "purple").save(s_dir / "img2.jpg")
    Image.new("RGB", (10, 10), "cyan").save(s_dir / "img3.png")

    t1_before = md5(t_dir / "img1.png")
    t2_before = md5(t_dir / "img2.jpg")
    t3_before = md5(t_dir / "img3.png")

    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup",
        stdin="i\ny\nn\n\n", cwd=project
    )

    assert t1_before != md5(t_dir / "img1.png"), "img1 should be overwritten (y)"
    assert t2_before == md5(t_dir / "img2.jpg"), "img2 should stay (n)"
    assert t3_before == md5(t_dir / "img3.png"), "img3 should stay (enter=skip)"
    r.ok("import + interactive each = y overwrites, n skips, enter skips")


def test_rename_overwrite_flag_enter(r):
    """rename: 带 --overwrite，直接回车=跳过"""
    project = init_project("t_rename_flag_enter")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "a.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "b.png")

    b_before = md5(img_dir / "b.png")
    ret, out = run_cmd(
        "brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b --overwrite",
        stdin="\n", cwd=project
    )

    assert b_before == md5(img_dir / "b.png"), "b.png should not change"
    assert (img_dir / "a.png").exists(), "a.png should exist"
    r.ok("rename + --overwrite + enter = skip (safe default)")


def test_rename_dry_run(r):
    """rename: --dry-run 不修改任何文件"""
    project = init_project("t_rename_dryrun")
    img_dir = project / "assets/images"
    Image.new("RGB", (100, 100), "red").save(img_dir / "logo.png")
    Image.new("RGB", (50, 50), "blue").save(img_dir / "photo.jpg")

    files_before = sorted(f.name for f in img_dir.iterdir())
    hashes_before = {f.name: md5(f) for f in img_dir.iterdir()}

    ret, out = run_cmd(
        "brand-kit rename assets/images --theme dark --name asset --dry-run",
        cwd=project
    )

    files_after = sorted(f.name for f in img_dir.iterdir())
    hashes_after = {f.name: md5(f) for f in img_dir.iterdir()}

    assert files_before == files_after, "file list should not change"
    assert hashes_before == hashes_after, "file contents should not change"
    assert "Dry-Run" in out, "output should mention Dry-Run"
    assert "源哈希" in out or "哈希" in out, "output should show hash info"
    r.ok("rename --dry-run = no file changes, shows diff info")


def test_import_overwrite_all_skip(r):
    """import: 不带 --overwrite，选全部跳过（只跳覆盖的，新文件照常）"""
    project = init_project("t_import_skip")
    target = project / "assets/images/default/logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    src_dir = project / "import_src"
    src_dir.mkdir()

    Image.new("RGB", (200, 200), "red").save(target)
    Image.new("RGB", (80, 80), "blue").save(src_dir / "logo.png")
    Image.new("RGB", (60, 60), "green").save(src_dir / "icon.png")

    target_before = md5(target)
    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup",
        stdin="s\n", cwd=project
    )

    assert target_before == md5(target), "existing target should not change (skipped)"
    assert (project / "assets/images/default/icon.png").exists(), "new file should be created"
    assert "跳过" in out and "新增" in out, "summary should show 跳过 and 新增"
    r.ok("import + all skip = existing stays, new files created")


def test_import_overwrite_all_yes(r):
    """import: 不带 --overwrite，选全部覆盖"""
    project = init_project("t_import_yes")
    target = project / "assets/images/default/logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    src_dir = project / "import_src"
    src_dir.mkdir()

    Image.new("RGB", (200, 200), "red").save(target)
    Image.new("RGB", (80, 80), "blue").save(src_dir / "logo.png")
    Image.new("RGB", (60, 60), "green").save(src_dir / "icon.png")

    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup",
        stdin="a\n", cwd=project
    )

    assert md5(target) == md5(src_dir / "logo.png"), "target should be overwritten"
    assert (project / "assets/images/default/icon.png").exists(), "new file should be created"
    assert "覆盖" in out and "新增" in out, "summary should show 覆盖 and 新增"
    r.ok("import + all overwrite = files imported, summary correct")


def test_import_overwrite_flag_enter(r):
    """import: 带 --overwrite，直接回车=跳过"""
    project = init_project("t_import_flag_enter")
    target = project / "assets/images/default/logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    src_dir = project / "import_src"
    src_dir.mkdir()

    Image.new("RGB", (200, 200), "red").save(target)
    Image.new("RGB", (80, 80), "blue").save(src_dir / "logo.png")

    target_before = md5(target)
    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup --overwrite",
        stdin="\n", cwd=project
    )

    assert target_before == md5(target), "target should not change"
    r.ok("import + --overwrite + enter = skip (safe default)")


def test_import_dry_run(r):
    """import: --dry-run 不修改任何文件"""
    project = init_project("t_import_dryrun")
    target = project / "assets/images/default/logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    src_dir = project / "import_src"
    src_dir.mkdir()

    Image.new("RGB", (200, 200), "red").save(target)
    Image.new("RGB", (80, 80), "blue").save(src_dir / "logo.png")
    Image.new("RGB", (60, 60), "green").save(src_dir / "photo.jpg")

    target_before = md5(target)
    target_dir_files_before = list((project / "assets/images/default").iterdir())

    ret, out = run_cmd(
        "brand-kit import import_src --type image --theme default --no-dedup --dry-run",
        cwd=project
    )

    assert target_before == md5(target), "target should not change"
    target_dir_files_after = list((project / "assets/images/default").iterdir())
    assert len(target_dir_files_before) == len(target_dir_files_after), "no new files"
    assert "Dry-Run" in out, "output should mention Dry-Run"
    r.ok("import --dry-run = no file changes, shows diff info")


def test_resize_overwrite_all_skip(r):
    """resize: 不带 --overwrite，选全部跳过"""
    project = init_project("t_resize_skip")
    src = project / "assets/images/photo.png"
    out_dir = project / "output/resized/default"
    out_dir.mkdir(parents=True)

    Image.new("RGB", (200, 200), "green").save(src)
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")

    thumb_before = md5(out_dir / "photo_50x50.png")
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default",
        stdin="s\n", cwd=project
    )

    assert thumb_before == md5(out_dir / "photo_50x50.png"), "thumb should not change"
    r.ok("resize + all skip = no change")


def test_resize_overwrite_all_yes(r):
    """resize: 不带 --overwrite，选全部覆盖"""
    project = init_project("t_resize_yes")
    src = project / "assets/images/photo.png"
    out_dir = project / "output/resized/default"
    out_dir.mkdir(parents=True)

    Image.new("RGB", (200, 200), "green").save(src)
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")

    thumb_before = md5(out_dir / "photo_50x50.png")
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default",
        stdin="a\n", cwd=project
    )

    assert thumb_before != md5(out_dir / "photo_50x50.png"), "thumb should be regenerated"
    assert "覆盖" in out, "summary should show 覆盖"
    r.ok("resize + all overwrite = file regenerated, summary correct")


def test_resize_overwrite_flag_enter(r):
    """resize: 带 --overwrite，直接回车=跳过"""
    project = init_project("t_resize_flag_enter")
    src = project / "assets/images/photo.png"
    out_dir = project / "output/resized/default"
    out_dir.mkdir(parents=True)

    Image.new("RGB", (200, 200), "green").save(src)
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")

    thumb_before = md5(out_dir / "photo_50x50.png")
    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50 --theme default --overwrite",
        stdin="\n", cwd=project
    )

    assert thumb_before == md5(out_dir / "photo_50x50.png"), "thumb should not change"
    r.ok("resize + --overwrite + enter = skip (safe default)")


def test_resize_dry_run(r):
    """resize: --dry-run 不修改任何文件"""
    project = init_project("t_resize_dryrun")
    src = project / "assets/images/photo.png"
    out_dir = project / "output/resized/default"
    out_dir.mkdir(parents=True)

    Image.new("RGB", (200, 200), "green").save(src)
    Image.new("RGB", (50, 50), "black").save(out_dir / "photo_50x50.png")

    thumb_before = md5(out_dir / "photo_50x50.png")
    files_before = list(out_dir.iterdir())

    ret, out = run_cmd(
        "brand-kit resize assets/images --sizes 50x50,100x100 --theme default --dry-run",
        cwd=project
    )

    assert thumb_before == md5(out_dir / "photo_50x50.png"), "existing thumb should not change"
    files_after = list(out_dir.iterdir())
    assert len(files_before) == len(files_after), "no new files"
    assert "Dry-Run" in out, "output should mention Dry-Run"
    r.ok("resize --dry-run = no file changes, shows diff info")


def main():
    r = TestResult()

    print("=" * 50)
    print("Brand Kit 全面测试：覆盖安全 & 批处理审计")
    print("=" * 50)

    print()
    print("--- rename 命令 ---")
    test_rename_overwrite_all_skip(r)
    test_rename_overwrite_all_yes(r)
    test_rename_overwrite_each(r)
    test_rename_overwrite_flag_enter(r)
    test_rename_dry_run(r)

    print()
    print("--- import 命令 ---")
    test_import_overwrite_all_skip(r)
    test_import_overwrite_all_yes(r)
    test_import_overwrite_each(r)
    test_import_overwrite_flag_enter(r)
    test_import_dry_run(r)

    print()
    print("--- resize 命令 ---")
    test_resize_overwrite_all_skip(r)
    test_resize_overwrite_all_yes(r)
    test_resize_overwrite_flag_enter(r)
    test_resize_dry_run(r)

    ok = r.summary()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
