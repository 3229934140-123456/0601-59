import os
import sys
import subprocess
import hashlib
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent


def get_file_hash(file_path: Path) -> str:
    if not file_path.exists():
        return "NOT_EXISTS"
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def create_test_image(path: Path, color: str, size=(100, 100)):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=color)
    img.save(path)


def run_cmd(cmd: str, stdin_input: str = None, cwd: str = None) -> tuple:
    result = subprocess.run(
        cmd, shell=True, capture_output=True,
        encoding="utf-8", errors="replace",
        input=stdin_input, cwd=str(cwd) if cwd else None
    )
    return result.returncode, result.stdout + result.stderr


def init_project(project_name: str) -> Path:
    import shutil
    project_path = BASE_DIR / project_name
    if project_path.exists():
        shutil.rmtree(project_path)
    project_path.mkdir(parents=True)
    run_cmd(f"brand-kit init my_project --path {project_path}")
    return project_path


def cleanup_project(project_path: Path):
    import shutil
    if project_path.exists():
        shutil.rmtree(project_path)


def test_rename():
    print("\n" + "=" * 60)
    print("1. rename 覆盖确认测试")
    print("=" * 60)

    project = init_project("test_rename_overwrite")
    images_dir = project / "assets/images"
    passed = 0
    total = 0

    def reset_files():
        create_test_image(images_dir / "a.png", "red", size=(100, 100))
        create_test_image(images_dir / "b.png", "blue", size=(50, 50))

    tests = [
        ("不带 --overwrite, 选 n", "", "n\n", True),
        ("不带 --overwrite, 直接回车", "", "\n", True),
        ("不带 --overwrite, 选 y", "", "y\n", False),
        ("带 --overwrite, 选 n", "--overwrite", "n\n", True),
        ("带 --overwrite, 选 y", "--overwrite", "y\n", False),
    ]

    for name, extra_args, user_input, should_skip in tests:
        total += 1
        reset_files()
        b_before = get_file_hash(images_dir / "b.png")

        cmd = f"brand-kit rename assets/images --pattern custom --custom-pattern \"b\" --name b {extra_args}"
        ret, output = run_cmd(cmd, stdin_input=user_input, cwd=project)

        b_after = get_file_hash(images_dir / "b.png")
        a_exists = (images_dir / "a.png").exists()

        ok = True
        if should_skip:
            if b_after != b_before:
                print(f"  ✗ {name}: b.png 被意外修改了")
                ok = False
            if not a_exists:
                print(f"  ✗ {name}: a.png 被意外移动了")
                ok = False
        else:
            if b_after == b_before:
                print(f"  ✗ {name}: b.png 未被覆盖")
                ok = False
            if a_exists:
                print(f"  ✗ {name}: a.png 未被重命名")
                ok = False

        if ok:
            print(f"  ✓ {name}")
            passed += 1
        else:
            short_out = output[:200].replace("\n", " ")
            print(f"     输出: {short_out}")

    cleanup_project(project)
    print(f"\n  结果: {passed}/{total} 通过")
    return passed == total


def test_import():
    print("\n" + "=" * 60)
    print("2. import 覆盖确认测试")
    print("=" * 60)

    project = init_project("test_import_overwrite")
    target = project / "assets/images/default/logo.png"
    source_dir = project / "import_src"
    source_dir.mkdir(exist_ok=True)
    passed = 0
    total = 0

    tests = [
        ("不带 --overwrite, 选 n", "", "n\n", True),
        ("不带 --overwrite, 直接回车", "", "\n", True),
        ("不带 --overwrite, 选 y", "", "y\n", False),
        ("带 --overwrite, 选 n", "--overwrite", "n\n", True),
        ("带 --overwrite, 选 y", "--overwrite", "y\n", False),
    ]

    for name, extra_args, user_input, should_skip in tests:
        total += 1
        create_test_image(target, "red", size=(200, 200))
        create_test_image(source_dir / "logo.png", "blue", size=(80, 80))
        target_before = get_file_hash(target)
        source_hash = get_file_hash(source_dir / "logo.png")

        cmd = f"brand-kit import import_src --type image --theme default --no-dedup {extra_args}"
        ret, output = run_cmd(cmd, stdin_input=user_input, cwd=project)

        target_after = get_file_hash(target)

        ok = True
        if should_skip:
            if target_after != target_before:
                print(f"  ✗ {name}: 目标文件被意外修改了")
                ok = False
        else:
            if target_after != source_hash:
                print(f"  ✗ {name}: 目标文件未被正确覆盖")
                ok = False

        if ok:
            print(f"  ✓ {name}")
            passed += 1
        else:
            short_out = output[:200].replace("\n", " ")
            print(f"     输出: {short_out}")

    cleanup_project(project)
    print(f"\n  结果: {passed}/{total} 通过")
    return passed == total


def test_resize():
    print("\n" + "=" * 60)
    print("3. resize 覆盖确认测试")
    print("=" * 60)

    project = init_project("test_resize_overwrite")
    source = project / "assets/images/photo.png"
    create_test_image(source, "green", size=(200, 200))

    output_dir = project / "output/resized/default"
    output_dir.mkdir(parents=True, exist_ok=True)
    passed = 0
    total = 0

    tests = [
        ("不带 --overwrite, 选 n", "", "n\n", True),
        ("不带 --overwrite, 直接回车", "", "\n", True),
        ("不带 --overwrite, 选 y", "", "y\n", False),
        ("带 --overwrite, 选 n", "--overwrite", "n\n", True),
        ("带 --overwrite, 选 y", "--overwrite", "y\n", False),
    ]

    for name, extra_args, user_input, should_skip in tests:
        total += 1
        create_test_image(output_dir / "photo_50x50.png", "black", size=(50, 50))
        thumb_before = get_file_hash(output_dir / "photo_50x50.png")

        cmd = f"brand-kit resize assets/images --sizes 50x50 --theme default {extra_args}"
        ret, output = run_cmd(cmd, stdin_input=user_input, cwd=project)

        thumb_after = get_file_hash(output_dir / "photo_50x50.png")

        ok = True
        if should_skip:
            if thumb_after != thumb_before:
                print(f"  ✗ {name}: 旧缩略图被意外修改了")
                ok = False
        else:
            if thumb_after == thumb_before:
                print(f"  ✗ {name}: 缩略图未重新生成")
                ok = False

        if ok:
            print(f"  ✓ {name}")
            passed += 1
        else:
            short_out = output[:200].replace("\n", " ")
            print(f"     输出: {short_out}")

    cleanup_project(project)
    print(f"\n  结果: {passed}/{total} 通过")
    return passed == total


def main():
    print("\n" + "=" * 60)
    print("Brand Kit 覆盖确认自动化测试")
    print("=" * 60)

    results = {}
    results["rename"] = test_rename()
    results["import"] = test_import()
    results["resize"] = test_resize()

    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    all_passed = True
    for cmd, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {cmd:10s} {status}")
        all_passed = all_passed and passed

    print()
    if all_passed:
        print("✓ 所有测试通过！")
        return 0
    else:
        print("✗ 部分测试失败！")
        return 1


if __name__ == "__main__":
    sys.exit(main())
