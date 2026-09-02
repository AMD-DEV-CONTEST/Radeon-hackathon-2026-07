import { defineStore } from "pinia";
import {
  analyzeChapter,
  autosaveChapter,
  buildChapterChangeSet,
  createChapter,
  createChapterLocalization as createChapterLocalizationApi,
  getChapter,
  listChapterLocalizations,
  listChapters,
  listChapterVersions,
  saveChapter,
} from "../api/chapters.js";
import { confirmChangeSet } from "../api/changesets.js";
import { getAuthStatus } from "../api/auth.js";
import { activateBook, activateDatabase, getActiveBook, getActiveDatabase, getBooks, getDatabases, getStats, getTimeline } from "../api/settings.js";
import { currentLocale, translate } from "../i18n/index.js";

const DRAFT_KEY = "aetherdb_workspace_draft";
const CHAPTER_META_KEY = "aetherdb_chapter_meta";
const AI_SETUP_KEY = "aetherdb_ai_setup";

function savedTime(value = new Date()) {
  const raw = String(value);
  const normalized = raw.includes("T") ? raw : `${raw.replace(" ", "T")}Z`;
  const date = value instanceof Date ? value : new Date(normalized);
  if (Number.isNaN(date.getTime())) return translate("刚刚");
  return date.toLocaleTimeString(currentLocale(), { hour: "2-digit", minute: "2-digit" });
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "") || fallback;
  } catch {
    return fallback;
  }
}

export const useAppStore = defineStore("app", {
  state: () => ({
    sidebarCollapsed: false,
    stats: null,
    timeline: [],
    activeDatabase: null,
    activeBook: null,
    databases: [],
    books: [],
    chapters: [],
    activeChapter: null,
    chapterLocalizations: [],
    chapterLocalizationsLoading: false,
    chapterVersions: [],
    chapterLoading: false,
    chapterSaving: false,
    chapterDirty: false,
    chapterError: "",
    analysisLoading: false,
    confirmingChangeSet: false,
    recentDocuments: [],
    recentWorlds: [],
    draftContent: localStorage.getItem(DRAFT_KEY) || "",
    chapterMeta: loadJson(CHAPTER_META_KEY, {
      title: "",
      volume: translate("第一卷"),
      chapterNo: translate("第 1 章"),
    }),
    immersiveWriting: false,
    pendingChangeSet: null,
    aiSetup: loadJson(AI_SETUP_KEY, {
      initialized: false,
      mode: "hybrid",
      provider: "",
      profile: "通用",
    }),
    lastSavedAt: null,
    actionMessage: "",
    backendAvailable: null,
    authStatus: null,
    authStatusLoading: false,
    loading: false,
  }),
  getters: {
    currentWorldName(state) {
      return state.activeBook?.title || state.activeDatabase?.name || state.activeDatabase?.title || translate("未选择世界");
    },
    currentWorldMode(state) {
      return state.activeBook?.status || state.activeDatabase?.status || translate("创作模式");
    },
    todayWords(state) {
      return state.draftContent.trim().length;
    },
    writingActivity(state) {
      const stats = state.stats || {};
      const todayWords = stats.today_words ?? stats.writing_today_words;
      const streakDays = stats.streak_days ?? stats.writing_streak_days;
      return {
        todayWords: Number.isFinite(Number(todayWords)) ? Number(todayWords) : null,
        streakDays: Number.isFinite(Number(streakDays)) ? Number(streakDays) : null,
      };
    },
    chapterTitle(state) {
      return state.chapterMeta.title || translate("未命名章节");
    },
    chapterLanguageCode(state) {
      return state.activeChapter?.language_code || "zh-CN";
    },
    chapterLocalizationStatus(state) {
      return state.activeChapter?.translation_status || "approved";
    },
    isChapterGroupActive(state) {
      return (chapter) => Boolean(
        chapter?.content_group_id
        && chapter.content_group_id === state.activeChapter?.content_group_id
      );
    },
    aiConfigured(state) {
      return Boolean(state.aiSetup?.initialized);
    },
    hasCapability(state) {
      return (capability) => Boolean(state.authStatus?.capabilities?.includes(capability));
    },
    isLocalOwner(state) {
      return Boolean(
        state.authStatus?.authenticated
        && state.authStatus?.deployment_enabled
        && state.authStatus?.effective_role === "owner",
      );
    },
    canEnterImmersive(state) {
      return Boolean(state.activeDatabase?.database_id && state.activeBook?.book_id);
    },
    overviewStats(state) {
      const stats = state.stats || {};
      return {
        entities: stats.total_entities || 0,
        relations: stats.total_relations || 0,
        events: stats.timeline_events || 0,
        timeline: stats.timeline_events || 0,
        tags: Array.isArray(stats.top_tags) ? stats.top_tags.length : 0,
        documents: state.recentDocuments.length,
      };
    },
  },
  actions: {
    async loadAuthStatus() {
      this.authStatusLoading = true;
      try {
        this.authStatus = await getAuthStatus();
        this.backendAvailable = true;
        return this.authStatus;
      } catch {
        this.authStatus = null;
        this.backendAvailable = false;
        return null;
      } finally {
        this.authStatusLoading = false;
      }
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed;
    },
    setDraftContent(value) {
      this.draftContent = value;
      this.chapterDirty = true;
      localStorage.setItem(DRAFT_KEY, value);
    },
    setChapterMeta(patch) {
      this.chapterMeta = { ...this.chapterMeta, ...patch };
      this.chapterDirty = true;
      localStorage.setItem(CHAPTER_META_KEY, JSON.stringify(this.chapterMeta));
    },
    setImmersiveWriting(value) {
      this.immersiveWriting = value;
    },
    requestImmersiveWriting() {
      if (!this.canEnterImmersive) {
        this.notifyAction(translate("请先选择要编辑的世界，再进入沉浸式创作"));
        return false;
      }
      this.immersiveWriting = true;
      return true;
    },
    async selectWorld(world) {
      if (!world) return false;
      this.loading = true;
      try {
        const databaseId = world.databaseId || world.database_id || (world.kind === "database" ? world.id : null);
        const bookId = world.bookId || world.book_id || (world.kind === "book" ? world.id : null);
        if (databaseId) await activateDatabase(databaseId);
        await activateBook(bookId || "default");
        await this.fetchDashboard();
        this.notifyAction(translate("已进入世界：{title}", { title: world.title }));
        return true;
      } catch (error) {
        this.notifyAction(error?.message || translate("无法切换世界，请检查服务连接"));
        return false;
      } finally {
        this.loading = false;
      }
    },
    setAiSetup(patch) {
      this.aiSetup = { ...this.aiSetup, ...patch };
      localStorage.setItem(AI_SETUP_KEY, JSON.stringify(this.aiSetup));
    },
    applyChapter(chapter) {
      this.activeChapter = chapter;
      this.draftContent = chapter?.content || "";
      this.chapterMeta = {
        title: chapter?.title || "",
        volume: chapter?.volume_id || translate("未分卷"),
        chapterNo: translate("第 {number} 章", { number: chapter?.chapter_index || 1 }),
      };
      this.chapterDirty = false;
      this.chapterError = "";
      this.lastSavedAt = chapter?.updated_at ? savedTime(chapter.updated_at) : null;
      localStorage.setItem(DRAFT_KEY, this.draftContent);
      localStorage.setItem(CHAPTER_META_KEY, JSON.stringify(this.chapterMeta));
    },
    applyChapterLocalizationState(localization) {
      if (!localization || !this.activeChapter) return;
      this.activeChapter = { ...this.activeChapter, ...localization };
      const index = this.chapterLocalizations.findIndex(
        (item) => item.chapter_id === this.activeChapter.chapter_id,
      );
      if (index >= 0) {
        this.chapterLocalizations.splice(index, 1, {
          ...this.chapterLocalizations[index],
          ...localization,
        });
      }
    },
    async loadChapters(bookId = this.activeBook?.book_id, { preserveSelection = true } = {}) {
      if (!bookId) {
        this.chapters = [];
        this.activeChapter = null;
        return;
      }
      this.chapterLoading = true;
      this.chapterError = "";
      try {
        const response = await listChapters(bookId);
        this.chapters = response?.chapters || [];
        const current = preserveSelection
          ? this.chapters.find((item) => (
            item.chapter_id === this.activeChapter?.chapter_id
            || (
              item.content_group_id
              && item.content_group_id === this.activeChapter?.content_group_id
            )
          ))
          : null;
        const next = current || this.chapters.at(-1);
        if (next) {
          const nextChapterId = (
            current?.content_group_id === this.activeChapter?.content_group_id
            && this.activeChapter?.chapter_id
          ) ? this.activeChapter.chapter_id : next.chapter_id;
          await this.openChapter(nextChapterId);
        }
        else {
          this.activeChapter = null;
          this.chapterLocalizations = [];
          this.chapterVersions = [];
          this.pendingChangeSet = null;
        }
        this.recentDocuments = [...this.chapters].reverse().slice(0, 5).map((item) => ({
          id: item.chapter_id,
          title: item.title,
          type: translate("第 {number} 章", { number: item.chapter_index || 1 }),
          updatedAt: item.updated_at || "",
        }));
      } catch (error) {
        this.chapterError = error?.message || translate("章节列表加载失败");
      } finally {
        this.chapterLoading = false;
      }
    },
    async openChapter(chapterId) {
      if (!chapterId) return false;
      this.chapterLoading = true;
      this.chapterError = "";
      try {
        const response = await getChapter(chapterId);
        this.applyChapter(response?.chapter || response);
        await this.loadChapterLocalizations(chapterId);
        this.pendingChangeSet = null;
        this.chapterVersions = [];
        return true;
      } catch (error) {
        this.chapterError = error?.message || translate("章节读取失败");
        return false;
      } finally {
        this.chapterLoading = false;
      }
    },
    async loadChapterLocalizations(chapterId = this.activeChapter?.chapter_id) {
      if (!chapterId) {
        this.chapterLocalizations = [];
        return [];
      }
      this.chapterLocalizationsLoading = true;
      try {
        const response = await listChapterLocalizations(chapterId);
        this.chapterLocalizations = response?.localizations || [];
        return this.chapterLocalizations;
      } catch (error) {
        this.chapterError = error?.message || translate("章节语言版本加载失败");
        return [];
      } finally {
        this.chapterLocalizationsLoading = false;
      }
    },
    async switchChapterLocalization(chapterId) {
      if (!chapterId || chapterId === this.activeChapter?.chapter_id) return true;
      if (this.chapterDirty) {
        const saved = await this.autosaveCurrentChapter(true);
        if (!saved) return false;
      }
      return this.openChapter(chapterId);
    },
    async createChapterLanguageVersion(languageCode) {
      const baseChapterId = this.activeChapter?.source_chapter_id
        || this.activeChapter?.chapter_id;
      if (!baseChapterId || !this.hasCapability("manage_translations")) {
        this.notifyAction(translate("当前会话不能管理章节语言版本"));
        return null;
      }
      if (this.chapterDirty) {
        const saved = await this.autosaveCurrentChapter(true);
        if (!saved) return null;
      }
      this.chapterLocalizationsLoading = true;
      try {
        const response = await createChapterLocalizationApi(baseChapterId, {
          language_code: languageCode,
        });
        this.chapterLocalizations = response?.localizations || [];
        this.applyChapter(response?.chapter);
        this.chapterVersions = [];
        this.pendingChangeSet = null;
        this.notifyAction(translate("新的章节语言版本已创建，请填写标题和正文"));
        return response?.chapter || null;
      } catch (error) {
        this.chapterError = error?.message || translate("创建章节语言版本失败");
        this.notifyAction(this.chapterError);
        return null;
      } finally {
        this.chapterLocalizationsLoading = false;
      }
    },
    async createChapterDraft(title = translate("新章节")) {
      const bookId = this.activeBook?.book_id;
      if (!bookId) {
        this.notifyAction(translate("请先选择作品，再创建章节"));
        return null;
      }
      this.chapterLoading = true;
      try {
        const created = await createChapter(bookId, { title });
        await this.loadChapters(bookId, { preserveSelection: false });
        if (created?.chapter_id && this.activeChapter?.chapter_id !== created.chapter_id) {
          await this.openChapter(created.chapter_id);
        }
        this.notifyAction(translate("新章节已创建"));
        return created;
      } catch (error) {
        this.chapterError = error?.message || translate("章节创建失败");
        this.notifyAction(this.chapterError);
        return null;
      } finally {
        this.chapterLoading = false;
      }
    },
    async saveCurrentChapter() {
      const bookId = this.activeBook?.book_id;
      if (!bookId) {
        this.notifyAction(translate("请先选择作品，再保存正文"));
        return false;
      }
      this.chapterSaving = true;
      this.chapterError = "";
      try {
        if (!this.activeChapter?.chapter_id) {
          const created = await createChapter(bookId, { title: this.chapterTitle || translate("新章节") });
          this.activeChapter = {
            ...created,
            chapter_index: created.chapter_index || this.chapters.length + 1,
          };
        }
        const saved = await saveChapter(this.activeChapter.chapter_id, {
          title: this.chapterTitle,
          content: this.draftContent,
          status: this.activeChapter.status || "draft",
        });
        this.activeChapter = {
          ...this.activeChapter,
          title: this.chapterTitle,
          content: this.draftContent,
          word_count: this.draftContent.length,
          updated_at: new Date().toISOString(),
        };
        this.applyChapterLocalizationState(saved?.localization);
        if (this.activeChapter.is_source !== 0) {
          const existingIndex = this.chapters.findIndex((item) => (
            item.chapter_id === this.activeChapter.chapter_id
            || (
              item.content_group_id
              && item.content_group_id === this.activeChapter.content_group_id
            )
          ));
          if (existingIndex >= 0) this.chapters.splice(existingIndex, 1, { ...this.activeChapter });
          else this.chapters.push({ ...this.activeChapter });
        }
        this.chapterDirty = false;
        this.lastSavedAt = savedTime();
        await this.loadChapterVersions();
        this.notifyAction(translate("章节正文已保存，尚未写入世界观设定"));
        return true;
      } catch (error) {
        this.chapterError = error?.message || translate("章节保存失败");
        this.notifyAction(this.chapterError);
        return false;
      } finally {
        this.chapterSaving = false;
      }
    },
    async autosaveCurrentChapter(force = false) {
      if (!this.activeChapter?.chapter_id || (!force && !this.chapterDirty) || this.chapterSaving) return false;
      this.chapterSaving = true;
      try {
        const saved = await autosaveChapter(this.activeChapter.chapter_id, {
          title: this.chapterTitle,
          content: this.draftContent,
        });
        this.activeChapter = {
          ...this.activeChapter,
          title: this.chapterTitle,
          content: this.draftContent,
          word_count: this.draftContent.length,
        };
        this.applyChapterLocalizationState(saved?.localization);
        this.chapterDirty = false;
        this.lastSavedAt = savedTime();
        return true;
      } catch (error) {
        this.chapterError = error?.message || translate("自动保存失败");
        return false;
      } finally {
        this.chapterSaving = false;
      }
    },
    async loadChapterVersions() {
      if (!this.activeChapter?.chapter_id) {
        this.chapterVersions = [];
        return [];
      }
      try {
        const response = await listChapterVersions(this.activeChapter.chapter_id);
        this.chapterVersions = response?.versions || [];
        return this.chapterVersions;
      } catch (error) {
        this.chapterError = error?.message || translate("版本历史加载失败");
        return [];
      }
    },
    async markSaved() {
      return this.saveCurrentChapter();
    },
    async createDraftChangeSet(analysisMode = "local_rules") {
      if (!this.activeChapter?.chapter_id) {
        this.notifyAction(translate("请先创建或选择章节"));
        return null;
      }
      if (this.draftContent.trim().length < 50) {
        this.notifyAction(translate("章节正文至少需要 50 字才能分析"));
        return null;
      }
      this.analysisLoading = true;
      this.chapterError = "";
      try {
        const saved = await this.autosaveCurrentChapter(true);
        if (!saved) throw new Error(this.chapterError || translate("分析前保存失败"));
        await analyzeChapter(this.activeChapter.chapter_id, analysisMode);
        this.pendingChangeSet = await buildChapterChangeSet(this.activeChapter.chapter_id);
        this.notifyAction(translate("章节分析完成，变更仍需确认后才会入库"));
        return this.pendingChangeSet;
      } catch (error) {
        this.chapterError = error?.message || translate("章节分析失败");
        this.notifyAction(this.chapterError);
        return null;
      } finally {
        this.analysisLoading = false;
      }
    },
    async confirmPendingChapterChangeSet() {
      const id = this.pendingChangeSet?.changeset_id;
      if (!id) return false;
      this.confirmingChangeSet = true;
      try {
        const result = await confirmChangeSet(id);
        this.pendingChangeSet = { ...this.pendingChangeSet, status: result?.status || "confirmed", result };
        this.notifyAction(translate("已将确认的设定变更写入当前世界"));
        await this.fetchStats();
        return true;
      } catch (error) {
        this.chapterError = error?.message || translate("设定变更确认失败");
        this.notifyAction(this.chapterError);
        return false;
      } finally {
        this.confirmingChangeSet = false;
      }
    },
    notifyAction(message) {
      this.actionMessage = message;
      window.clearTimeout(this._messageTimer);
      this._messageTimer = window.setTimeout(() => {
        this.actionMessage = "";
      }, 2200);
    },
    async fetchStats() {
      this.loading = true;
      try {
        this.stats = await getStats();
        this.backendAvailable = true;
      } catch (error) {
        this.backendAvailable = false;
      } finally {
        this.loading = false;
      }
    },
    async fetchDashboard() {
      this.loading = true;
      const tasks = await Promise.allSettled([
        getStats(),
        getTimeline(),
        getActiveDatabase(),
        getActiveBook(),
        getDatabases(),
        getBooks(),
      ]);

      const [stats, timeline, activeDatabase, activeBook, databases, books] = tasks;
      this.backendAvailable = tasks.some((task) => task.status === "fulfilled");

      if (stats.status === "fulfilled") this.stats = stats.value;
      if (timeline.status === "fulfilled") {
        this.timeline = Array.isArray(timeline.value) ? timeline.value : [];
        this.recentDocuments = this.timeline.slice(-5).reverse().map((item) => ({
          id: item.id || item.entity_id || item.title,
          title: item.title || item.entity_title || translate("未命名文档"),
          type: item.era || translate("文档"),
          updatedAt: item.created_at || item.updated_at || "",
        }));
      }
      if (databases.status === "fulfilled") this.databases = databases.value?.databases || (Array.isArray(databases.value) ? databases.value : []);
      if (books.status === "fulfilled") {
        const databaseId = books.value?.database_id || null;
        const list = books.value?.books || (Array.isArray(books.value) ? books.value : []);
        this.books = list.map((item) => ({ ...item, database_id: item.database_id || databaseId }));
      }
      if (activeDatabase.status === "fulfilled") {
        const activeId = activeDatabase.value?.active_database_id || activeDatabase.value?.database_id;
        this.activeDatabase = this.databases.find((item) => item.database_id === activeId) || (activeId ? { database_id: activeId, name: activeId } : null);
      }
      if (activeBook.status === "fulfilled") {
        const activeId = activeBook.value?.active_book_id || activeBook.value?.book_id;
        this.activeBook = this.books.find((item) => item.book_id === activeId) || null;
      }

      if (this.activeBook?.book_id) await this.loadChapters(this.activeBook.book_id);
      else {
        this.chapters = [];
        this.activeChapter = null;
      }

      const worldSources = [...this.books, ...this.databases].filter(Boolean);
      this.recentWorlds = worldSources.slice(0, 4).map((item) => ({
        id: item.book_id || item.database_id || item.id || item.name || item.title,
        kind: item.book_id ? "book" : "database",
        databaseId: item.database_id || null,
        bookId: item.book_id || null,
        title: item.title || item.name || item.id || translate("未命名世界"),
        subtitle: item.status || item.description || translate("最近访问"),
        entities: item.entity_count || item.entities || this.stats?.total_entities || 0,
        relations: item.relation_count || item.relations || this.stats?.total_relations || 0,
        events: item.event_count || item.events || this.stats?.timeline_events || 0,
      }));

      this.loading = false;
    },
  },
});
