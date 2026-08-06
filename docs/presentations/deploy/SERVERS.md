# 服务器：43.156.102.67（MetaHub 机 · 兼挂 Investor Deck）

| 端口/路径 | 服务 | 说明 |
|-----------|------|------|
| **:3000** | New-API / MetaHub | **勿动**，Docker `new-api` |
| **:80 `/deck/`** | BotverseX Investor Deck | 静态 HTML，与 3000 隔离 |
| :443 | 预留 HTTPS | 可与 80 同样挂 `/deck/` |

Deck 文件目录：`/var/www/botversex-deck/`

对外链接：

- http://43.156.102.67/deck/ — 入口（两版 Deck）
- http://43.156.102.67/deck/story-deck.html — **愿景故事**（无融资）
- http://43.156.102.67/deck/investor-deck.html — **投资人 Seed**
