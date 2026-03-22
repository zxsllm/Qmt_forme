# AI Trade - 量化交易系统

A股量化交易系统，目标是从数据采集、策略研究、模拟交易到实盘交易的全链路覆盖。

## 当前进度

- [x] Phase 1: 数据层 — 日线/分钟K线/指标/指数/行业分类全量入库
- [ ] Phase 2: 前端交易控制台 (P2-Core)
- [ ] Phase 3: 实时数据流 + 模拟交易引擎
- [ ] Phase 4: 策略框架与回测系统
- [ ] Phase 5: QMT实盘桥接
- [ ] Phase 6: AI/ML策略增强

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.10+, FastAPI, SQLAlchemy 2.0 (async) |
| 数据库 | PostgreSQL 18+ (分钟数据按月分区) |
| 数据源 | Tushare Pro (需总包API权限) |
| 前端 (规划) | React 19, TypeScript, Vite, Ant Design 5 |
| 实盘 (规划) | QMT (xtquant) |

## 快速开始

### 1. 环境准备

- Python 3.10+
- PostgreSQL 18+
- Tushare Pro 账号 (总包权限)

### 2. 安装

```bash
git clone https://github.com/zxsllm/Qmt_forme.git
cd Qmt_forme

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r backend/requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 PostgreSQL 密码和 Tushare Token
```

确保 PostgreSQL 中已创建 `ai_trade` 数据库：

```sql
CREATE DATABASE ai_trade;
```

### 4. 初始化数据库

```bash
cd backend
alembic upgrade head
cd ..
```

分钟数据分区表（Alembic 之外）：

```bash
python scripts/create_min_partitions.py
```

### 5. 拉取数据

```bash
# 基础数据 + 半年日线
python scripts/init_data.py

# 每日指标 + 指数 + 行业分类
python scripts/pull_batch1.py

# 1分钟K线 (全量约3小时, 支持断点续拉)
python scripts/pull_minutes.py           # 全量
python scripts/pull_minutes.py --test 5  # 测试5只
python scripts/pull_minutes.py --resume  # 断点续拉
```

### 6. 启动后端

```bash
cd backend
uvicorn app.main:app --port 8000
```

访问 http://localhost:8000/health 验证。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/{ts_code}/daily` | 个股日线+基本面 |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场当日截面 |
| GET | `/api/v1/index/{ts_code}/daily` | 指数日线 |
| GET | `/api/v1/classify/sw?level=L1` | 申万行业分类 |

## 项目结构

```
backend/
  app/
    core/           — 配置、数据库连接
    shared/models/  — SQLAlchemy 模型
    shared/data/    — DataLoader 统一数据访问层
    research/data/  — Tushare 数据拉取服务
    main.py         — FastAPI 入口
  alembic/          — 数据库迁移

scripts/
  init_data.py              — 基础数据 + 日线拉取
  pull_batch1.py            — 指标 + 指数 + 行业拉取
  create_min_partitions.py  — 分钟表分区创建
  pull_minutes.py           — 分钟K线拉取
```

## License

MIT
