# ShapeAI 后端 API 镜像
# 构建: docker build -t xingke-api .

FROM python:3.11-slim

# 国内服务器默认走阿里云 PyPI 镜像; 海外构建可用:
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple/ .
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# editable 安装使 shapeai 包解析到 /app/shapeai,
# 项目内 data/ 与 .shapeai/ 运行时目录落在 /app 下, 由 compose 卷持久化
COPY pyproject.toml ./
COPY shapeai ./shapeai
RUN pip install --index-url ${PIP_INDEX_URL} -e .

EXPOSE 28900

# 启动前循环执行数据库迁移(PG/MySQL/Milvus 就绪前会失败重试), 成功后再启动 API
CMD ["sh", "-c", "until python -m shapeai.migrate; do echo '[migrate] 数据库未就绪, 5秒后重试...'; sleep 5; done && exec shapeai serve --host 0.0.0.0 --port 28900"]
