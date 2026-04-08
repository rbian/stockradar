#!/usr/bin/env python3
"""Fix run_bot.py: gh-pages sync + _save_nav recursion bug"""
fp = '/home/node/.openclaw/workspace/research/stockradar/scripts/run_bot.py'
with open(fp) as f:
    c = f.read()

# Fix 1: Add gh-pages sync after master push
old1 = """                subprocess.run(["git", "push", "origin", "master"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                logger.info("GitHub Pages \u5df2\u66f4\u65b0")"""

new1 = """                subprocess.run(["git", "push", "origin", "master"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                # Sync to gh-pages branch
                subprocess.run(["git", "fetch", "origin", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "checkout", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                import shutil as _shutil
                for _fname in ["index.html", "data.json"]:
                    _shutil.copy2(str(PROJECT_ROOT / "docs" / _fname),
                                 str(PROJECT_ROOT / _fname))
                subprocess.run(["git", "add", "index.html", "data.json"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                subprocess.run(["git", "commit", "-m",
                              "pages: " + str(__import__('datetime').date.today())],
                              cwd=str(PROJECT_ROOT), timeout=10, capture_output=True)
                subprocess.run(["git", "push", "origin", "gh-pages"],
                              cwd=str(PROJECT_ROOT), timeout=30)
                subprocess.run(["git", "checkout", "master"],
                              cwd=str(PROJECT_ROOT), timeout=10)
                logger.info("GitHub Pages \u5df2\u66f4\u65b0")"""

c = c.replace(old1, new1)

# Fix 2: _save_nav infinite recursion
old2 = """                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                _save_nav(tracker, dq)"""

new2 = """                nav_file = PROJECT_ROOT / 'data' / 'nav_state_balanced.json'
                import json as _json2
                nav_file.write_text(_json2.dumps(tracker.to_dict(), ensure_ascii=False, indent=2))"""

c = c.replace(old2, new2)

with open(fp, 'w') as f:
    f.write(c)

# Verify
with open(fp) as f:
    v = f.read()
if 'gh-pages' in v and '_save_nav(tracker, dq)' not in v:
    print("OK: both fixes applied")
else:
    print("WARNING: fixes may not have applied correctly")
    if 'gh-pages' in v:
        print("  - gh-pages sync: OK")
    else:
        print("  - gh-pages sync: FAILED")
    if '_save_nav(tracker, dq)' in v:
        print("  - _save_nav recursion: FAILED")
    else:
        print("  - _save_nav recursion: OK")
