"""阶段 4.5 — 资产分层规划(AssetPlanner)。

拆书+人物/场景设计之后, 让 LLM 扫全书章节, 判定每个角色/场景是【全书公共资产 public】还是
【某集私有临时资产 private】, 并列出每集用到哪些公共+私有。产物 bible/asset_registry.json:
  · 公共资产 → 全书一次生成、固定锚、跨集复用(同一角色跨集一致);
  · 私有资产 → 该集制作时现补, 仅本集引用;
  · 是"修改权限分层"的依据(逐集/QC 返工只能改私有=本级资产, 改公共需显式全局操作)。
LLM 不可用/失败 → 保守回退: 全部判 public(全书一次生成最安全), per_episode 按分集规划全覆盖。
"""
from __future__ import annotations

import json

from .base import Agent
from ..llm_client import TIER_STRUCTURE
from ..schemas import (ChapterManifest, StoryBible, CharacterBible, SceneBible,
                       AssetRegistry, AssetEntry)

_SYS = (
    "你是短剧资产规划师。给你一本小说的章节清单(每章人物/地点/摘要)、可用角色清单、可用场景清单、分集规划。"
    "判定每个角色/场景是【全书公共资产 public】还是【某集私有临时资产 private】, 并列出它出现在哪些集、"
    "每集要用到哪些公共+私有资产。\n判定规则:\n"
    "- 在 >=2 集出现 → public; 只在 1 集出现 → private。\n"
    "- 主角 / 第一人称 POV 角色 → 恒 public。\n"
    "- 高频道具化场景(家 / 公司 / 常用车内 等) → public。\n"
    "char_id / scene_id 只能用给定的, 禁止发明新 id。只输出 JSON, schema:\n"
    '{"characters":[{"char_id":str,"scope":"public"|"private","episodes":[Eid...],"freq":int,"owner_episode":Eid?}],'
    '"scenes":[{"scene_id":str,"scope":"public"|"private","episodes":[Eid...]}],'
    '"per_episode":{"<Eid>":{"public":[id...],"private":[id...]}}}')


class AssetPlanner(Agent):
    name = "资产规划"
    tier = TIER_STRUCTURE

    def run(self, manifest: ChapterManifest, bible: StoryBible,
            chars: CharacterBible, scenes: SceneBible) -> AssetRegistry:
        reg = self._plan(manifest, bible, chars, scenes)
        reg.save(self.ctx.paths.bible / "asset_registry.json")
        npub = len(reg.public_char_ids()) + len(reg.public_scene_ids())
        ntotal = len(reg.characters) + len(reg.scenes)
        self.info(f"资产规划: {len(reg.characters)} 角色 / {len(reg.scenes)} 场景, "
                  f"公共 {npub}/{ntotal}, 集 {list(reg.per_episode)}")
        return reg

    @staticmethod
    def _episode_plan(bible: StoryBible, manifest: ChapterManifest):
        return bible.episode_plan or [{"episode_id": "E001",
                                       "chapters": [c.chapter_id for c in manifest.chapters[:1]]}]

    def _fallback(self, manifest, bible, chars, scenes) -> AssetRegistry:
        """保守回退: 全部 public, 每集用全部角色/场景(全书一次生成、都复用, 最安全)。"""
        cids = [c.char_id for c in chars.characters]
        sids = [s.scene_id for s in scenes.scenes]
        eids = [e.get("episode_id") for e in self._episode_plan(bible, manifest) if e.get("episode_id")]
        return AssetRegistry(
            novel_title=manifest.novel_title,
            characters=[AssetEntry(asset_id=i, scope="public", episodes=eids) for i in cids],
            scenes=[AssetEntry(asset_id=i, scope="public", episodes=eids) for i in sids],
            per_episode={e: {"public": cids + sids, "private": []} for e in eids})

    def _plan(self, manifest, bible, chars, scenes) -> AssetRegistry:
        cids = [c.char_id for c in chars.characters]
        sids = [s.scene_id for s in scenes.scenes]
        if self.ctx.dry_run or (not cids and not sids):
            return self._fallback(manifest, bible, chars, scenes)
        plan = self._episode_plan(bible, manifest)
        rows = [{"chapter_id": c.chapter_id, "characters": c.characters,
                 "locations": c.locations, "summary": (c.summary or "")[:200]}
                for c in manifest.chapters]
        user = (f"分集规划: {json.dumps(plan, ensure_ascii=False)}\n"
                f"章节: {json.dumps(rows, ensure_ascii=False)}\n"
                f"可用角色(char_id:name): "
                f"{json.dumps({c.char_id: c.name for c in chars.characters}, ensure_ascii=False)}\n"
                f"可用场景(scene_id:name): "
                f"{json.dumps({s.scene_id: s.name for s in scenes.scenes}, ensure_ascii=False)}")
        try:
            res = self.ctx.llm.chat_json(self.tier, _SYS, user)
            reg = self._coerce(res, manifest, cids, sids, plan)
            if reg:
                return reg
        except Exception as e:  # noqa: BLE001
            self.warn(f"资产规划 LLM 失败, 回退全公共: {e}")
        return self._fallback(manifest, bible, chars, scenes)

    def _coerce(self, res, manifest, cids, sids, plan):
        """把 LLM 输出清洗成 AssetRegistry: 只留合法 id; 漏判的补 public; per_episode 缺则反推。"""
        if not isinstance(res, dict):
            return None

        def entries(arr, valid):
            out, seen = [], set()
            for x in (arr or []):
                if not isinstance(x, dict):
                    continue
                aid = x.get("char_id") or x.get("scene_id") or x.get("asset_id") or x.get("id")
                if aid not in valid or aid in seen:
                    continue
                seen.add(aid)
                out.append(AssetEntry(
                    asset_id=aid, scope=("private" if x.get("scope") == "private" else "public"),
                    episodes=[e for e in (x.get("episodes") or []) if isinstance(e, str)],
                    freq=int(x.get("freq") or 0), owner_episode=str(x.get("owner_episode") or "")))
            return out

        ch = entries(res.get("characters"), set(cids))
        sc = entries(res.get("scenes"), set(sids))
        for i in cids:                                  # 漏判 → 默认 public(保守、受保护)
            if i not in {e.asset_id for e in ch}:
                ch.append(AssetEntry(asset_id=i, scope="public"))
        for i in sids:
            if i not in {e.asset_id for e in sc}:
                sc.append(AssetEntry(asset_id=i, scope="public"))

        valid = set(cids) | set(sids)
        per = res.get("per_episode") if isinstance(res.get("per_episode"), dict) else {}
        per_clean = {}
        for eid, obj in per.items():
            if not isinstance(obj, dict):
                continue
            per_clean[eid] = {"public": [i for i in (obj.get("public") or []) if i in valid],
                              "private": [i for i in (obj.get("private") or []) if i in valid]}
        if not per_clean:                               # LLM 没给 → 用 episodes 反推
            for eid in [e.get("episode_id") for e in plan if e.get("episode_id")]:
                per_clean[eid] = {
                    "public": [e.asset_id for e in ch + sc
                               if e.scope == "public" and (not e.episodes or eid in e.episodes)],
                    "private": [e.asset_id for e in ch + sc
                                if e.scope == "private" and eid in e.episodes]}
        return AssetRegistry(novel_title=manifest.novel_title, characters=ch, scenes=sc,
                             per_episode=per_clean)
