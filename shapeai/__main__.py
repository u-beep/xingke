"""ShapeAI CLI 入口 — 支持 python -m shapeai。"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
