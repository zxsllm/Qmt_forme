# VoidCore 深空玻璃拟态 UI 规范

本文件是前端目录下给 Codex 使用的局部 harness，内容与 `frontend/CLAUDE.md` 保持同一设计语言。

修改前端 UI 时必须遵循以下设计语言，保持深空玻璃拟态一致性。

## 色板

| 变量 | 色值 | 用途 |
|------|------|------|
| `--bg-deep` | `#07111a` | 最深底色 |
| `--bg-mid` | `#102231` | 中层面板底色 |
| `--bg-soft` | `rgba(16,34,49,0.78)` | 柔和背景 |
| `--line-soft` | `rgba(148,186,215,0.18)` | 边框 |
| `--line-strong` | `rgba(121,200,246,0.42)` | 聚焦边框 |
| `--text-main` | `#e6f1fa` | 主文本 |
| `--text-soft` | `#93a9bc` | 辅助文本 |
| `--blue` | `#6bc7ff` | 主操作 |
| `--purple` | `#b48cff` | 次级 |
| `--orange` | `#ffbf75` | 警告 |
| `--red` | `#ff6f91` | 危险 |
| `--special` | `#7ce1f2` | 特殊高亮 |

## 玻璃面板

```css
background: linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92));
border: 1px solid var(--line-soft);
box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 48px rgba(0,0,0,0.34);
backdrop-filter: blur(10px);
border-radius: 22px;
padding: 18px;
```

## 圆角: 大面板 24px / 卡片 22px / 子卡片 18px / 按钮 14px / 胶囊 999px

## 按钮

- 主: `background: linear-gradient(135deg, #2481bd, #3b61d6)`
- 次: `background: linear-gradient(135deg, #2f4354, #22303b)`
- 警告: `background: linear-gradient(135deg, #99502c, #b54f61)`
- Hover: `transform: translateY(-1px)` | Disabled: `opacity: 0.5`

## 输入框

```css
border-radius: 14px; border: 1px solid rgba(255,255,255,0.1);
background: rgba(6,14,22,0.82); color: var(--text-main);
```

聚焦: `border-color: rgba(121,200,246,0.46); box-shadow: 0 0 0 3px rgba(56,132,180,0.16)`

## 间距: 面板 padding 18px / 面板间 gap 18px / 子元素 gap 10-12px

## 排版: 标题 14px/700 / 正文 13px / 辅助 11-12px / 日志 12px

## 禁止

- 纯白背景或高饱和纯色块
- `border-radius < 10px` 的面板
- 去掉 `backdrop-filter: blur` 或 `inset box-shadow`
- `> 1px` 的边框宽度 (除选中态)
- `transition` 超过 `120ms` 或用 `linear`
