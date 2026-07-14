# ruff: noqa: E402

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import upgrade_business_database


def main() -> int:
    upgrade_business_database()
    print("[OK] 业务数据库初始化完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
