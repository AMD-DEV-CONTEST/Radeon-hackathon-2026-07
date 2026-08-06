# Investor Deck · 部署在 MetaHub 服务器

**主机**：`43.156.102.67`（腾讯云新加坡，Ubuntu + Docker MetaHub）

| 服务 | 地址 |
|------|------|
| MetaHub / New-API | `http://43.156.102.67:3000` — **部署脚本不修改** |
| **入口** | `http://43.156.102.67/deck/` |
| **愿景故事**（无融资） | `http://43.156.102.67/deck/story-deck.html` |
| **投资人 Seed** | `http://43.156.102.67/deck/investor-deck.html` |

Deck 走 **Nginx 80 端口 `/deck/`** 静态目录，与 `:3000` 完全隔离。

## 一键部署

```bash
ssh-copy-id ubuntu@43.156.102.67   # 首次
./scripts/deploy-investor-deck.sh
```

## 文件布局（服务器上）

```
/var/www/botversex-deck/
  investor-deck.html
  investor-seed-2026.html
  assets/
```

## 本地预览

```bash
cd docs/presentations/deploy && docker compose up --build
# http://localhost:8080/investor-deck.html
```

## 导出 PPT 用 PNG

```bash
cd docs/presentations/scripts && npm install && node export-deck-slides.mjs
```
