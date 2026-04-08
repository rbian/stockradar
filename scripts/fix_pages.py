fp = '/home/node/.openclaw/workspace/research/stockradar/scripts/run_bot.py'
with open(fp) as f:
    lines = f.readlines()

# Line 331 (0-indexed 330) is the logger.info line  
# Replace it with gh-pages sync block BEFORE the logger.info
ghpages_block = """                # Sync to gh-pages branch
                subprocess.run(["git", "fetch", "origin", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "checkout", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                import shutil
                for fname in ["index.html", "data.json"]:
                    shutil.copy2(str(PROJECT_ROOT / "docs" / fname),
                                 str(PROJECT_ROOT / fname))
                subprocess.run(["git", "add", "index.html", "data.json"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "commit", "-m",
                              f"pages: {__import__('datetime').date.today()}"],
                              cwd=str(PROJECT_ROOT), timeout=10, capture_output=True)
                subprocess.run(["git", "push", "origin", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                subprocess.run(["git", "checkout", "master"],
                              cwd=str(PROJECT_ROOT), timeout=10)
"""

new_lines = []
for i, line in enumerate(lines):
    if i == 330:  # the logger.info line - insert before
        new_lines.append(ghpages_block)
    new_lines.append(line)

with open(fp, 'w') as f:
    f.writelines(new_lines)
print("OK")
