"""临时脚本：列出当前数据库中的全部用户。"""

from shapeai.database import pg_cursor

with pg_cursor() as cur:
    cur.execute(
        "SELECT id, username, nickname, created_at::date, "
        "COALESCE(last_login_at::date::text, '—') FROM users ORDER BY id"
    )
    rows = cur.fetchall()

print(f'{"id":<4} {"username":<26} {"nickname":<14} {"created":<12} last_login')
print("-" * 72)
for r in rows:
    print(f"{r[0]:<4} {str(r[1]):<26} {str(r[2] or '—'):<14} {str(r[3]):<12} {r[4]}")
print(f"共 {len(rows)} 个用户")
