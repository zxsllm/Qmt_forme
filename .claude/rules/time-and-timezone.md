# 时间与时区

- 一律本地 CST（UTC+8）。不说 UTC、不换算、不解释时差。
- A 股时刻表：09:30 开 / 11:30 午休 / 13:00 续 / 14:55 尾盘 / 15:00 收。
- 前端日期用 `getFullYear/Month/Date`，禁 `toISOString().slice(0,10)`。
- cron / 日志 / DB 时间戳统一 `Asia/Shanghai`。
