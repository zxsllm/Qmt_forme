# AI Trade - A股量化交易系统

全链路 A 股量化交易平台，覆盖数据采集、策略研究、模拟交易、自动化复盘到实盘交易。

## 当前进度

- [x] Phase 1: 数据层 — 日线/分钟K线/指标/指数/行业分类全量入库
- [x] Phase 2: 前端交易控制台 — K线多周期+排行榜+新闻公告+拼音搜索
- [x] Phase 3: 实时数据流 + 模拟交易引擎
- [x] Phase 4: 策略框架与回测系统 (含 4.5 模拟盘闭环 / 4.6 日运行生命周期 / 4.7 A股规则合规 / 4.8 四维能力建设 / 4.9 数据增强)
- [x] Phase 5: 自动化复盘与早盘计划 — Claude 驱动的每日复盘+早盘计划+pgvector 历史对比
- [ ] Phase 6: QMT实盘桥接
- [ ] Phase 7: AI/ML策略增强

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + asyncpg |
| 数据库 | PostgreSQL 18 + Alembic + pgvector, Redis (Memurai) |
| 数据源 | Tushare Pro (满权限) |
| 前端 | React 19, TypeScript 5.9, Vite 8, Ant Design 6, TailwindCSS 4, klinecharts 9.8 |
| 状态管理 | Zustand + React Query |
| 实盘 (规划) | QMT (xtquant) |

## 快速开始

### 1. 环境准备

- Python 3.12+
- PostgreSQL 18+ (需启用 pgvector 扩展)
- Redis (Windows 下用 Memurai)
- Node.js 20+
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
cd frontend && npm install && cd ..
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 PostgreSQL 密码和 Tushare Token
```

### 4. 初始化数据库

```bash
cd backend
alembic upgrade head
cd ..

# 分钟数据分区表 (Alembic 之外)
python scripts/create_min_partitions.py
```

### 5. 启动

```bash
# 后端
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 前端 (另一个终端)
cd frontend
npm run dev
```

- 后端: http://localhost:8000
- 前端: http://localhost:5173

## 核心功能

- **数据采集**: 28+ 个 Tushare 数据同步函数，scheduler 定时调度
- **交易控制台**: 多周期K线、持仓管理、委托下单、风控面板
- **策略回测**: 策略框架 + 回测引擎 + 绩效分析
- **模拟交易**: OMS 订单管理 + 撮合引擎 + T+1/涨跌停/整手合规
- **四维分析**: 消息面(新闻分类) + 基本面(财务/行业画像) + 情绪面(涨停/连板/游资) + 技术面(MACD/RSI/KDJ/BOLL)
- **自动化复盘**: 每日收盘后自动生成复盘报告，36维特征向量 + pgvector 历史相似行情匹配
- **早盘计划**: 每日开盘前自动生成交易计划，含仓位建议、进出场条件、风控预警
- **数据健康**: 全量数据健康检查面板 + 自动修复

## 项目结构

```
backend/
  app/
    core/              — 配置、数据库连接、启动检查
    execution/         — 交易执行层 (OMS/撮合/风控/调度)
    research/          — 研究层 (回测/策略/数据拉取)
    shared/            — 共享层 (模型/数据加载/分析引擎/API)
  alembic/             — 数据库迁移

frontend/
  src/
    pages/             — 页面组件 (Dashboard/Trading/Sentiment/...)
    components/        — 通用组件
    stores/            — Zustand 状态

scripts/               — 数据拉取/CLI/运维脚本
```

## License

MIT
