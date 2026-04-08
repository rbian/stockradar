def deploy_to_ghpages():
    """导出数据并推送到 gh-pages 分支"""
    import shutil, tempfile
    output = export()
    proj = str(PROJECT)

    # 先备份最新文件到临时目录（checkout gh-pages后docs/会被覆盖）
    tmp_dir = tempfile.mkdtemp()
    for fname in ["index.html", "data.json"]:
        shutil.copy2(str(PROJECT / "docs" / fname), str(PROJECT / tmp_dir / fname))

    # Commit docs/ to master
    subprocess.run(["git", "add", "docs/"], cwd=proj, timeout=10)
    try:
        subprocess.run(["git", "commit", "-m", "pages: data update"],
                      cwd=proj, timeout=10, capture_output=True)
        subprocess.run(["git", "push", "origin", "master"], cwd=proj, timeout=30)
    except Exception:
        pass  # no changes to commit

    # Deploy to gh-pages — 从临时目录复制
    subprocess.run(["git", "fetch", "origin", "gh-pages"], cwd=proj, timeout=10)
    subprocess.run(["git", "checkout", "gh-pages"], cwd=proj, timeout=10)
    for fname in ["index.html", "data.json"]:
        shutil.copy2(str(PROJECT / tmp_dir / fname), str(PROJECT / fname))
    shutil.rmtree(tmp_dir, ignore_errors=True)
    subprocess.run(["git", "add", "index.html", "data.json"], cwd=proj, timeout=10)
    try:
        subprocess.run(["git", "commit", "-m", f"pages: {output['updated']}"],
                      cwd=proj, timeout=10, capture_output=True)
        subprocess.run(["git", "push", "origin", "gh-pages"], cwd=proj, timeout=30)
        print("gh-pages 已部署")
    except Exception:
        print("gh-pages 无变化")
    subprocess.run(["git", "checkout", "master"], cwd=proj, timeout=10)


if __name__ == '__main__':
    deploy_to_ghpages()
