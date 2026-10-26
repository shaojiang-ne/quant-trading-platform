FROM registry.cn-hangzhou.aliyuncs.com/wangruchao/python:3.12.7-slim

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 配置阿里云 apt 镜像源（兼容 sources.list 和 debian.sources 两种格式）
RUN if [ -f /etc/apt/sources.list ]; then \
        sed -i 's@/deb.debian.org/@/mirrors.aliyun.com/@g' /etc/apt/sources.list && \
        sed -i 's@/security.debian.org/@/mirrors.aliyun.com/@g' /etc/apt/sources.list; \
    fi && \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's@/deb.debian.org/@/mirrors.aliyun.com/@g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's@/security.debian.org/@/mirrors.aliyun.com/@g' /etc/apt/sources.list.d/debian.sources; \
    fi

RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set install.trusted-host mirrors.aliyun.com

# 安装系统依赖（bcrypt/pymysql 需要 gcc/libffi）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
# 排除：vnpy（x86_64 预编译库 + PySide6 GUI）、mootdx（要求 httpx<0.26 与 openai 冲突）
# 补充：排除 vnpy/mootdx 后缺失的间接依赖
COPY requirements.txt .
RUN grep -v -E 'vnpy|mootdx' requirements.txt > requirements.docker.txt && \
    echo "numpy>=1.24.0" >> requirements.docker.txt && \
    echo "pandas>=2.0.0" >> requirements.docker.txt && \
    echo "requests>=2.31.0" >> requirements.docker.txt && \
    echo "urllib3>=2.0.0" >> requirements.docker.txt && \
    echo "akshare>=1.10.0" >> requirements.docker.txt && \
    pip install --no-cache-dir -r requirements.docker.txt

# 复制项目代码
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
