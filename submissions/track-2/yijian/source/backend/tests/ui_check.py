# -*- coding: utf-8 -*-
"""复盘工作台 UI 自动验证（Playwright）。

- 三种宽度截图：1600×900 / 1366×768 / 390×844
- 控制台必须零报错
- 关键手列表点击 → 跳到第 78 手，棋盘出现金圈标记，胜率同步
- file:// 打开（无后端）时回退本地演示且不报错

用法：先启动后端(端口 8600)，再 python tests/ui_check.py <输出目录>
"""
import os
import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)
BASE = os.getenv("GOMENTOR_BASE", "http://127.0.0.1:8600")
WEB_FILE = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "web", "index.html"))

failures = []


def check(name, cond, detail=""):
    tag = "通过" if cond else "失败"
    print(f"[{tag}] {name}" + (f" —— {detail}" if detail else ""))
    if not cond:
        failures.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---- 后端模式：三宽度截图 ----
    for label, w, h in [
        ("1600", 1600, 900), ("1366", 1366, 768),
        ("1280", 1280, 720), ("390", 390, 844),
    ]:
        page = browser.new_page(viewport={"width": w, "height": h})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(400)
        check(f"{label} 控制台零报错", not errors, "; ".join(errors[:3]))
        # 横向溢出检查
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"{label} 无横向溢出", overflow <= 0, f"超出 {overflow}px")
        if label in ("1366", "1280"):
            page.evaluate("""() => {
              libraryPanel.classList.remove("collapsed");
              focusReviewWorkspace();
            }""")
            compact_width = page.locator("#libraryPanel").bounding_box()["width"]
            check(f"{label} 进入复盘后自动收起棋谱库并保留轨道",
                  compact_width <= 50
                  and page.locator(".library-rail").is_visible(),
                  f"棋谱库宽度 {compact_width}px")
        if label == "1280":
            board_box = page.locator("#board").bounding_box()
            rail_box = page.locator(".insight-rail").bounding_box()
            side_box = page.locator(".side").bounding_box()
            composer_box = page.locator("#mentorQaForm").bounding_box()
            summary_box = page.locator('[data-testid="move-summary"]').bounding_box()
            messages_box = page.locator("#mentorQaMessages").bounding_box()
            check("1280×720 三栏互不重叠且棋盘保持主视觉",
                  rail_box["x"] + rail_box["width"] <= board_box["x"]
                  and board_box["x"] + board_box["width"] <= side_box["x"]
                  and board_box["width"] >= 500,
                  f"关键栏={rail_box}, 棋盘={board_box}, 教练栏={side_box}")
            check("1280×720 问棋输入框完整可见",
                  composer_box is not None
                  and composer_box["y"] + composer_box["height"] <= h,
                  str(composer_box))
            check("1280×720 讲解摘要、Agent 消息与输入台同屏",
                  summary_box is not None and summary_box["height"] >= 40
                  and messages_box is not None and messages_box["height"] >= 64
                  and composer_box["y"] >= messages_box["y"] + messages_box["height"],
                  f"讲解={summary_box}, 消息={messages_box}, 输入={composer_box}")
        if label == "390":
            page.evaluate(
                "localStorage.setItem('yijian-library-collapsed', '1')")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(250)
            check("390 侧栏默认收起", page.locator("#libraryPanel").bounding_box()["x"] < 0)
            check("390 不继承桌面折叠样式",
                  "collapsed" not in
                  (page.locator("#libraryPanel").get_attribute("class") or ""))
            page.click("#sheetHandle")
            page.wait_for_timeout(250)
            mobile_workspace = page.locator(
                '[data-testid="agent-workspace"]').bounding_box()
            mobile_summary = page.locator(
                '[data-testid="move-summary"]').bounding_box()
            mobile_messages = page.locator("#mentorQaMessages").bounding_box()
            mobile_composer = page.locator(
                '[data-testid="agent-composer"]').bounding_box()
            check("390 展开围棋教练后讲解、消息与输入台同屏",
                  "sheet-open" in
                  (page.locator(".side").get_attribute("class") or "")
                  and mobile_workspace is not None
                  and mobile_summary is not None and mobile_summary["height"] >= 40
                  and mobile_messages is not None and mobile_messages["height"] >= 64
                  and mobile_composer is not None
                  and mobile_composer["y"] + mobile_composer["height"] <= h,
                  f"工作区={mobile_workspace}, 讲解={mobile_summary}, "
                  f"消息={mobile_messages}, 输入={mobile_composer}")
            page.click("#sheetHandle")
            page.wait_for_timeout(200)
            page.click("#libraryToggle")
            page.wait_for_timeout(250)
            check("390 侧栏以完整抽屉打开",
                  page.locator("#libraryPanel").bounding_box()["x"] == 0
                  and page.locator("#gameList").is_visible()
                  and page.locator("#libraryToggle").get_attribute("aria-expanded") == "true")
        page.screenshot(path=os.path.join(OUT, f"工作台-{label}.png"), full_page=True)
        page.close()

    # ---- 交互验证（1600 宽） ----
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_timeout(400)

    all_points = page.evaluate("""() => {
      const empty = new Int8Array(N * N);
      for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
        if (!playOnBoard(empty, 1, [c, r]).ok) return false;
      }
      return true;
    }""")
    check("all empty intersections accept moves", all_points)
    snap_points = page.evaluate("""() => {
      const matrix = svg.getScreenCTM();
      for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
        const p = new DOMPoint(px(c) + CELL * .49, px(r) - CELL * .49)
          .matrixTransform(matrix);
        const mapped = boardPointFromEvent({clientX:p.x, clientY:p.y});
        if (!mapped || mapped[0] !== c || mapped[1] !== r) return false;
      }
      return true;
    }""")
    check("whole board hit areas snap to intersections", snap_points)
    rule_reasons = page.evaluate("""() => {
      const occupied = new Int8Array(N * N);
      occupied[idx(9, 9)] = 1;
      const a = playOnBoard(occupied, 2, [9, 9]);
      const suicide = new Int8Array(N * N);
      for (const [c, r] of neighbors(9, 9)) suicide[idx(c, r)] = 2;
      const b = playOnBoard(suicide, 1, [9, 9]);
      let board = new Int8Array(N * N), ko = null;
      for (const [color, move] of [
        [1,[1,0]], [1,[0,1]], [2,[2,0]], [2,[1,1]], [1,[2,1]], [2,[0,0]],
      ]) {
        const played = playOnBoard(board, color, move, ko);
        if (!played.ok) return false;
        board = played.board; ko = played.ko;
      }
      const recapture = playOnBoard(board, 1, [1,0], ko);
      return a.reason === "occupied" && b.reason === "suicide"
        && recapture.reason === "ko";
    }""")
    check("only board rules reject moves with precise reason", rule_reasons)
    desktop_layout = page.evaluate("""() => {
      const insight = document.querySelector(".insight-rail").getBoundingClientRect();
      const board = document.querySelector(".boardwrap").getBoundingClientRect();
      const coach = document.querySelector(".side").getBoundingClientRect();
      const workspace = document.querySelector('[data-testid="agent-workspace"]').getBoundingClientRect();
      const summary = document.querySelector('[data-testid="move-summary"]').getBoundingClientRect();
      const composer = document.querySelector('[data-testid="agent-composer"]').getBoundingClientRect();
      const boardSvg = document.querySelector("#board").getBoundingClientRect();
      return {
        leftRail: insight.right <= board.left + 1,
        rightCoach: coach.left >= board.right - 1,
        mergedState: getComputedStyle(document.querySelector(".side-movestat")).display === "none"
          && document.querySelector("#coachContextBar").getClientRects().length > 0,
        stackInside: summary.top >= workspace.top && composer.bottom <= workspace.bottom + 1,
        boardSize: boardSvg.width,
        coachHeight: workspace.height,
        unwantedButtons: document.querySelectorAll("#explainRole,#refreshCoach,#personaTag").length,
      };
    }""")
    check(
        "desktop uses left insights, center board, full-height coach",
        desktop_layout["leftRail"] and desktop_layout["rightCoach"]
        and desktop_layout["mergedState"] and desktop_layout["stackInside"]
        and desktop_layout["boardSize"] > 600
        and desktop_layout["coachHeight"] > 700
        and desktop_layout["unwantedButtons"] == 0,
        str(desktop_layout),
    )

    chip = page.text_content("#engineChip")
    check("后端在线标识", "已就绪" in chip, chip)
    check("对局信息载入", "AlphaGo" in page.text_content("#gameInfo"))
    page.evaluate("""() => {
      window.__sgfMetadataExecuted = false;
      window.__originalGameInfo = {...S.info};
      const malicious = '<img src=x onerror="window.__sgfMetadataExecuted=true">';
      loadGame(
        S.moves.slice(),
        {...S.info, PB:malicious, EV:malicious},
        S.analysis,
        S.sgfText,
        S.currentLibraryId,
      );
    }""")
    malicious_game_info = page.text_content("#gameInfo")
    check("SGF PB/EV 元数据只作为纯文本显示",
          malicious_game_info.count("<img") == 2
          and page.locator("#gameInfo img").count() == 0
          and not page.evaluate("window.__sgfMetadataExecuted"),
          malicious_game_info)
    page.evaluate("""() => loadGame(
      S.moves.slice(),
      window.__originalGameInfo,
      S.analysis,
      S.sgfText,
      S.currentLibraryId,
    )""")
    check("桌面紧凑棋谱侧轨可见", page.locator(".library-rail").is_visible())
    page.click('button[data-rail-category="classics"]')
    page.wait_for_timeout(250)
    check("世界名局=25盘", page.locator("#gameList .game-item").count() == 25)
    page.click('button[data-category="recent"]')
    page.wait_for_timeout(250)
    check("近期职业=20个审核占位", page.locator("#gameList .editorial-slot").count() == 20)
    check("审核占位不可播放", page.locator("#gameList .game-item").count() == 0)
    page.click('button[data-category="mine"]')

    page.evaluate("""() => {
      window.__stoneSoundEvents = [];
      document.addEventListener("gomentor:stone-sound",
        event => window.__stoneSoundEvents.push(event.detail));
    }""")
    check("落子音效默认开启",
          page.locator("#soundToggle").get_attribute("aria-pressed") == "true")
    page.locator("#board").hover()
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(160)
    check("滚轮向后前进", page.text_content("#moveLabel").strip().startswith("1"))
    check("实战前进触发落子音效",
          page.evaluate("window.__stoneSoundEvents.length") == 1
          and page.evaluate("window.__stoneSoundEvents[0].source") == "real")
    page.mouse.wheel(0, -120)
    page.wait_for_timeout(160)
    check("滚轮向前回退", page.text_content("#moveLabel").strip().startswith("0"))
    check("回退不触发落子音效",
          page.evaluate("window.__stoneSoundEvents.length") == 1)
    page.click("#soundToggle")
    muted_count = page.evaluate("window.__stoneSoundEvents.length")
    check("落子音效可关闭并记忆",
          page.locator("#soundToggle").get_attribute("aria-pressed") == "false"
          and page.evaluate("localStorage.getItem('yijian-stone-sound-enabled')") == "0")
    page.click("#btnNext")
    check("下一手按钮可用", page.text_content("#moveLabel").strip().startswith("1"))
    check("静音后前进不触发音效",
          page.evaluate("window.__stoneSoundEvents.length") == muted_count)
    page.click("#btnPrev")
    check("上一手按钮可用", page.text_content("#moveLabel").strip().startswith("0"))
    page.click("#soundToggle")
    check("重新开启音效会试听并恢复记忆",
          page.locator("#soundToggle").get_attribute("aria-pressed") == "true"
          and page.evaluate("localStorage.getItem('yijian-stone-sound-enabled')") == "1"
          and page.evaluate("window.__stoneSoundEvents.at(-1).source") == "preview")
    check("棋盘下方按钮有足够点击高度",
          page.locator(".controls .btn").first.bounding_box()["height"] >= 40)
    page.click("#btnPlay")
    check("播放状态有明确反馈", "active" in page.locator("#btnPlay").get_attribute("class"))
    page.click("#btnPlay")

    page.click("#coachSettingsBtn")
    check("教学设定弹窗打开", page.locator("#coachDialog").is_visible())
    page.click("#coachClose")
    page.evaluate("showPerspectiveChoice()")
    page.click("#chooseBlack")
    check(
        "analysis mode choice",
        page.locator("#analysisModeStep").is_visible()
        and page.locator(".analysis-mode-btn").count() == 2,
    )
    check(
        "快速分析说明包含时间目标",
        "20～30 秒" in page.locator('.analysis-mode-btn[data-mode="fast"]').text_content(),
    )
    page.click("#analysisClose")
    page.route(
        "**/api/analysis/jobs/ui-cancel-test/cancel",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body="{}"
        ),
    )
    page.evaluate("""() => {
      showDialogStep("progress");
      setReviewLocked(true);
      renderAnalysisJob({
        status:"running", stage:"scan", mode:"fast", progress:42.6,
        currentTurn:96, totalTurns:204, rate:12.4, etaSeconds:8.2,
        message:"全盘扫描 96/205",
      });
      S.analysisJobId = "ui-cancel-test";
      S.analysisPoll = setTimeout(() => {}, 10000);
    }""")
    page.wait_for_timeout(450)
    check(
        "动态进度显示小数、速度与剩余时间",
        "%" in page.text_content("#analysisPercent")
        and "." in page.text_content("#analysisPercent")
        and "12.4 手/秒" in page.text_content("#analysisRate")
        and "约 8 秒" in page.text_content("#analysisEta")
        and page.locator("#analysisStages .active").count() == 1,
    )
    page.click("#analysisClose")
    page.wait_for_timeout(120)
    exit_state = page.evaluate("""() => ({
      open: document.querySelector("#analysisDialog").open,
      jobId: S.analysisJobId,
      poll: S.analysisPoll,
      locked: S.reviewLocked,
    })""")
    check(
        "analysis exits without reopening or leaving poll active",
        not exit_state["open"] and exit_state["jobId"] is None
        and exit_state["poll"] is None and not exit_state["locked"],
        str(exit_state),
    )
    page.locator('.library-view-tab[data-library-view="report"]').click()
    page.wait_for_timeout(120)
    check("全局报告移入最左棋谱栏",
          page.locator("#libraryPanel.report-view").count() == 1
          and page.locator("#globalPanel").is_visible())
    check("胜率趋势功能已移除",
          page.locator("#trendCard,#wrchart,[data-panel='trendPanel']").count() == 0)
    page.locator('.library-view-tab[data-library-view="games"]').click()
    page.wait_for_timeout(120)
    check("关键节点独立显示在棋盘左侧",
          page.locator(".insight-rail #keymoves").is_visible()
          and page.locator(".insight-rail #keymoves li").count() == 5)
    km_first = page.locator("#keymoves li").first
    check("关键手Top1=第78手", "78" in km_first.text_content(), km_first.text_content())
    km_first.click()
    page.wait_for_timeout(300)
    check("跳转到第78手", page.text_content("#moveLabel").strip().startswith("78"),
          page.text_content("#moveLabel"))
    check("着点显示 L11", "L11" in page.text_content("#coordLabel"),
          page.text_content("#coordLabel"))
    gold = page.locator('#marks circle[stroke="#b39055"]')
    check("第78手金圈标记", gold.count() == 1)
    page.evaluate("""() => {
      const node = {
        turn:78, color:"W", coord:"ki", actualMove:"L11",
        recommendedMove:"Q9", pv:["Q9","D4","Q4","D16"],
        winrateLoss:11.9, scoreLoss:4.2, severity:"major",
        phaseTags:["middle"], deepened:true,
      };
      S.report = {
        perspective:"W", losses:[node], visibleNodes:[node], turningPoints:[],
        phases:{
          joseki:[], opening:{start:1,end:45},
          middle:{start:46,end:135}, endgame:{start:136,end:180},
        },
      };
      setPos(78);
    }""")
    check("腾讯式当前手对照条可见",
          page.locator("#moveComparison").is_visible()
          and "S L11" in page.text_content("#actualMoveTag")
          and "AI 首选 J" in page.text_content("#aiMoveTag")
          and "11.9" in page.text_content("#moveLoss"))
    check("不同着时问棋默认明确绑定 AI 首选",
          page.locator('#qaTargetSwitch [data-qa-target="best"]').get_attribute(
              "aria-pressed") == "true"
          and "Q9" in page.text_content(
              '#qaTargetSwitch [data-qa-target="best"]'))
    sj_labels = page.evaluate(
        "[...document.querySelectorAll('#marks text')].map(item => item.textContent)")
    check("关键节点棋盘显示 S/J 对照", "S" in sj_labels and "J" in sj_labels,
          str(sj_labels))
    check("棋盘绿色 J 推荐点可直接点击",
          page.locator('[data-ai-variation="78"]').count() == 1)
    check("AI 首选可直接进入变化", page.locator("#aiMoveTag").is_enabled())
    sound_count_before_variation = page.evaluate("window.__stoneSoundEvents.length")
    page.locator('[data-ai-variation="78"]').click()
    page.wait_for_timeout(150)
    compare_variation = page.evaluate("""() => ({
      turn:S.cur, variation:!!S.variation, returnTurn:S.comparisonReturnTurn,
      returnEnabled:!document.querySelector("#btnReturn").disabled,
      step:S.variation?.step, total:S.variation?.pv?.length,
      playLabel:document.querySelector("#btnPlay").textContent,
    })""")
    check("绿色 J 自动回退并从变化第一手开始",
          compare_variation["turn"] == 77 and compare_variation["variation"]
          and compare_variation["returnTurn"] == 78
          and compare_variation["returnEnabled"]
          and compare_variation["step"] == 1
          and compare_variation["total"] == 4
          and compare_variation["playLabel"] == "播放变化",
          str(compare_variation))
    variation_context_text = page.text_content("#boardContextBar")
    check("进入 AI 变化后面包屑保留实战来源",
          "AI 变化" in variation_context_text
          and "实战第" in page.text_content("#boardBreadcrumb"),
          variation_context_text)
    keyboard_before = page.evaluate(
        "() => ({turn:S.cur, step:S.variation?.step})")
    for key in ("ArrowRight", "Home", "End"):
        page.press("#mentorQaInput", key)
    keyboard_after = page.evaluate(
        "() => ({turn:S.cur, step:S.variation?.step})")
    check("问棋输入中的导航键不会改变当前手或变化步",
          keyboard_after == keyboard_before,
          f"before={keyboard_before}, after={keyboard_after}")
    check("进入 AI 变化会触发落子音效",
          page.evaluate("window.__stoneSoundEvents.length")
          == sound_count_before_variation + 1
          and page.evaluate("window.__stoneSoundEvents.at(-1).source") == "variation")
    page.click("#btnNext")
    check("下一手逐手演示 AI 变化",
          page.evaluate("S.variation?.step") == 2
          and page.evaluate("window.__stoneSoundEvents.at(-1).source") == "variation")
    page.click("#btnPlay")
    page.wait_for_timeout(80)
    page.click("#btnPlay")
    check("播放键可自动演示 AI 变化",
          page.evaluate("S.variation?.step") >= 3)
    km_first.click()
    page.wait_for_timeout(80)
    auto_return = page.evaluate(
        "() => ({turn:S.cur, variation:!!S.variation, returnTurn:S.comparisonReturnTurn})")
    check("变化中点击关键节点会自动回实战",
          auto_return["turn"] == 78 and not auto_return["variation"]
          and auto_return["returnTurn"] is None, str(auto_return))
    page.click("#aiMoveTag")
    page.wait_for_timeout(80)
    page.click("#btnLast")
    page.click("#btnNext")
    boundary_hold = page.evaluate("""() => ({
      turn:S.cur, variation:!!S.variation, step:S.variation?.step,
      total:S.variation?.pv?.length, hint:document.querySelector("#variationHint").textContent,
    })""")
    check("变化末端继续前进仍保持研究层",
          boundary_hold["turn"] == 77 and boundary_hold["variation"]
          and boundary_hold["step"] == boundary_hold["total"]
          and "不会退出" in boundary_hold["hint"], str(boundary_hold))
    boundary_context_text = page.text_content("#boardContextBar")
    check("变化末端面包屑持续保留 AI 变化与实战来源",
          "AI 变化" in boundary_context_text
          and "实战第" in page.text_content("#boardBreadcrumb"),
          boundary_context_text)
    page.mouse.move(800, 400)
    page.mouse.wheel(0, 1200)
    boundary_wheel = page.evaluate(
        "() => ({turn:S.cur, variation:!!S.variation, step:S.variation?.step})")
    check("变化末端滚轮不会回实战",
          boundary_wheel["turn"] == 77 and boundary_wheel["variation"]
          and boundary_wheel["step"] == boundary_hold["total"], str(boundary_wheel))
    page.click("#btnReturn")
    page.wait_for_timeout(80)
    compare_return = page.evaluate(
        "() => ({turn:S.cur, variation:!!S.variation, returnTurn:S.comparisonReturnTurn})")
    check("结束变化后返回原实战手",
          compare_return["turn"] == 78 and not compare_return["variation"]
          and compare_return["returnTurn"] is None, str(compare_return))
    check("返回实战后棋盘面包屑恢复主线",
          page.text_content("#boardModeChip").strip() == "实战"
          and "主线" in page.text_content("#boardBreadcrumb")
          and "AI 变化" not in page.text_content("#boardContextBar"),
          page.text_content("#boardContextBar"))
    check("当前手作用讲解自动展开", "作用" in page.text_content("#roleExplanation"))
    check("无 gameId 的启动棋明确标为演示视图",
          "第 78 手" in page.text_content("#coachMsg")
          and "演示视图" in page.text_content("#coachMsg"))
    check("启动演示不冒充 KataGo 权威数值",
          "启动演示不属于权威教学证据"
          in page.text_content("#mentorQaFoot"))
    check("启动演示讲解正文不冒充 KataGo",
          "KataGo" not in page.text_content("#roleExplanation"))
    demo_evidence_text = page.text_content('[data-testid="evidence-katago"]')
    check("启动演示分析证据明确标记非 KataGo",
          "演示分析" in demo_evidence_text and "非 KataGo" in demo_evidence_text,
          demo_evidence_text)
    check("可信状态栏与证据入口常驻、详情默认收起",
          page.locator('[data-testid="trust-bar"]').is_visible()
          and page.locator('[data-testid="agent-evidence-toggle"]').is_visible()
          and not page.locator('[data-testid="evidence-panel"]').is_visible())
    page.click('[data-testid="agent-evidence-toggle"]')
    check("展开证据工具后四类事实边界完整可见",
          page.locator('[data-testid="evidence-panel"]').is_visible()
          and all(
              page.locator(f'[data-testid="{testid}"]').is_visible()
              for testid in (
                  "evidence-rules", "evidence-katago",
                  "evidence-heuristic", "evidence-expression",
              )
          ))
    panel_box = page.locator('[data-testid="evidence-panel"]').bounding_box()
    composer_box = page.locator('[data-testid="agent-composer"]').bounding_box()
    check("证据工具浮层不挤走或遮挡输入台",
          panel_box is not None and composer_box is not None
          and panel_box["y"] + panel_box["height"] <= composer_box["y"] + 1
          and composer_box["y"] + composer_box["height"] <=
              page.locator('[data-testid="agent-workspace"]').bounding_box()["y"]
              + page.locator('[data-testid="agent-workspace"]').bounding_box()["height"] + 1,
          f"证据={panel_box}, 输入={composer_box}")
    check("讲解方式可切换", page.locator("#mentorModeQuick option").count() == 4)
    page.click("#agentModeToggle")
    check("讲解方式按需展开且事实边界说明可见",
          page.locator("#agentModePanel").is_visible()
          and page.locator("#mentorModeQuick").is_visible()
          and "不改写 KataGo 事实" in page.text_content("#agentModePanel"))
    page.click("#agentModeClose")
    page.click('[data-testid="agent-evidence-toggle"]')
    check("基础棋理无需模型即可使用",
          page.input_value("#mentorModeQuick") in ("baseline", "local", "cloud", "compare")
          and len(page.text_content("#roleExplanation").strip()) > 20)
    check("讲解与问棋同屏显示",
          page.locator("#coachExplainView").is_visible()
          and page.locator("#mentorQaView").is_visible()
          and page.locator("#coachQaTab").count() == 0)
    check("问棋老师支持自由输入",
          page.locator("#mentorQaInput").is_visible()
          and page.locator("[data-qa-question]").count() == 4)
    check("问棋上下文绑定当前手", "第 78 手" in page.text_content("#mentorQaContext"))
    page.evaluate("""() => {
      S.qaMessages = [{role:'user', content:'为什么这手不好？', turn:S.cur}];
      S.qaBusy = true;
      renderQaMessages();
    }""")
    check("问棋等待态在对话流中清晰可见",
          page.locator('[data-testid="qa-thinking-card"]').is_visible()
          and "服务端证据" in page.text_content('[data-testid="qa-thinking-card"]')
          and "已等待 0 秒" in page.text_content('[data-testid="qa-thinking-card"]')
          and page.locator(".qa-thinking-cancel").is_visible()
          and page.locator("#mentorQaMessages").get_attribute("aria-busy") == "true"
          and page.locator("#mentorQaSend").is_disabled()
          and page.text_content("#mentorQaSend").strip() == "思考中")
    page.click(".qa-thinking-cancel")
    check("取消回答后等待态消失、输入恢复且保留上下文",
          page.locator('[data-testid="qa-thinking-card"]').count() == 0
          and page.locator("#mentorQaMessages").get_attribute("aria-busy") == "false"
          and not page.locator("#mentorQaSend").is_disabled()
          and page.text_content("#mentorQaSend").strip() == "发送"
          and "本次回答已取消" in page.text_content("#mentorQaMessages")
          and "第 78 手" in page.text_content("#mentorQaMessages"))
    page.evaluate("""() => {
      S.qaMessages = [];
      renderQaMessages();
    }""")
    page.evaluate("""() => {
      S.qaMessages = [{role:'assistant',
        content:'先说结论｜同屏追问测试。\\n为什么这样下｜角部争夺与边上扩张需要比较。', turn:S.cur,
        sourceLabel:'本地离线老师', actions:[], followUps:[]}];
      renderQaMessages();
    }""")
    qa_summary_box = page.locator("#coachExplainView").bounding_box()
    qa_messages_box = page.locator("#mentorQaMessages").bounding_box()
    qa_composer_box = page.locator("#mentorQaForm").bounding_box()
    check("产生追问后讲解摘要保留、消息区扩展且输入台不动",
          page.locator("#coachExplainView").is_visible()
          and qa_summary_box is not None and qa_summary_box["height"] >= 80
          and qa_messages_box is not None and qa_messages_box["height"] >= 120
          and qa_composer_box is not None
          and qa_composer_box["y"] + qa_composer_box["height"] <=
              page.locator('[data-testid="agent-workspace"]').bounding_box()["y"]
              + page.locator('[data-testid="agent-workspace"]').bounding_box()["height"] + 1
          and "同屏追问测试" in page.text_content("#mentorQaMessages"),
          f"讲解={qa_summary_box}, 消息={qa_messages_box}, 输入={qa_composer_box}")
    qa_reading_state = page.evaluate("""() => ({
      sections: document.querySelectorAll('#mentorQaMessages .qa-answer-section').length,
      fontSize: parseFloat(getComputedStyle(
        document.querySelector('#mentorQaMessages .qa-answer-section p')).fontSize),
      metaColumns: getComputedStyle(
        document.querySelector('#mentorQaMessages .qa-bubble-meta')).gridTemplateColumns,
    })""")
    check("专业回答按自适应标题分段且正文字号可读",
          qa_reading_state["sections"] == 2
          and qa_reading_state["fontSize"] >= 14
          and qa_reading_state["metaColumns"] != "none",
          str(qa_reading_state))
    page.evaluate("""() => {
      S.qaMessages = [{
        role:'assistant', turn:S.cur, sourceLabel:'本地离线老师',
        content:Array.from({length:36}, (_, i) =>
          `第 ${i + 1} 点：围绕当前局面的证据继续说明。`).join('\\n'),
        actions:[], followUps:[],
      }];
      renderQaMessages();
    }""")
    long_answer_state = page.evaluate("""() => {
      const messages = document.querySelector('#mentorQaMessages');
      const composer = document.querySelector('#mentorQaForm').getBoundingClientRect();
      const workspace = document.querySelector('[data-testid="agent-workspace"]')
        .getBoundingClientRect();
      return {
        scrolls: messages.scrollHeight > messages.clientHeight,
        composerInside: composer.bottom <= workspace.bottom + 1,
      };
    }""")
    check("长回答只滚动消息区且输入台持续可见",
          long_answer_state["scrolls"] and long_answer_state["composerInside"],
          str(long_answer_state))
    page.click("#mentorQaClear")
    check("作用讲解四项图例完整", all(
        label in page.text_content("#roleExplanation")
        for label in ["本手落子", "己方关联棋群", "对方受影响棋群", "影响区域"]))
    check("详细影响区默认收起",
          page.locator("#marks rect").count() == 0
          and page.locator("#roleHighlightToggle").get_attribute("aria-pressed") == "false"
          and not page.locator("#roleHighlightLegend").is_visible())
    if not page.locator("#roleHighlightToggle").is_visible():
        page.click('[data-testid="agent-evidence-toggle"]')
    page.click("#roleHighlightToggle")
    check("点击查看影响区后显示高亮",
          page.locator("#marks rect").count() >= 1
          and page.locator("#roleHighlightToggle").get_attribute("aria-pressed") == "true")
    page.click("#btnNext")
    check("换手后高亮自动收起",
          page.locator("#marks rect").count() == 0
          and page.locator("#roleHighlightToggle").get_attribute("aria-pressed") == "false")
    page.click("#btnPrev")
    page.click('[data-testid="agent-evidence-toggle"]')
    page.click("#roleHighlightToggle")
    page.click("#roleHighlightToggle")
    check("再次点击后收起高亮",
          page.locator("#marks rect").count() == 0
          and page.locator("#roleHighlightToggle").get_attribute("aria-pressed") == "false"
          and not page.locator("#roleHighlightLegend").is_visible())
    page.click(".agent-feedback-disclosure summary")
    page.click('[data-mentor-feedback="helpful"]')
    page.wait_for_timeout(150)
    check("演示棋不冒充权威证据保存反馈",
          "权威证据尚未就绪" in page.text_content("#mentorFeedbackNote"))
    stones = page.locator("#stones g.stone").count()
    check("第78手盘面子数=78", stones == 78, f"实际 {stones}")
    page.screenshot(path=os.path.join(OUT, "工作台-第78手定位.png"))

    # 播放/导航
    page.click("#btnLast")
    page.wait_for_timeout(200)
    check("跳到终局 180 手", page.text_content("#moveLabel").strip().startswith("180"))
    stones_end = page.locator("#stones g.stone").count()
    check("终局盘面子数=167(79黑+88白)", stones_end == 167, f"实际 {stones_end}")

    # ---- 权威教学瘦请求与变化定位 ----
    explain_payloads = []
    chat_payloads = []
    feedback_payloads = []

    def teaching_context(body):
        variation = body.get("variation") or []
        effective_turn = int(body["turn"]) + len(variation)
        context_id = (
            f"ctx-{body['gameId']}-{body['reportId']}-"
            f"{body['turn']}-{'-'.join(variation) or 'main'}"
        )
        return {
            "schemaVersion": "teaching-context-v6",
            "contextId": context_id,
            "gameId": body["gameId"],
            "reportId": body["reportId"],
            "reportRevision": "revision-authority",
            "positionHash": f"hash-{context_id}",
            "evidenceHash": "evidence-authority",
            "subject": {
                "baseTurn": body["turn"],
                "variation": variation,
                "effectiveTurn": effective_turn,
                "move": variation[-1] if variation else "L11",
                "player": "W",
            },
            "authority": {
                "source": "server", "reconstructed": True,
                "clientEvidenceAccepted": False,
            },
            "position": {
                "turn": effective_turn, "baseTurn": body["turn"],
                "variationDepth": len(variation), "toPlay": "黑",
                "phase": "中盘", "move": variation[-1] if variation else "L11",
                "boardSize": 19,
            },
            "facts": {
                "rules": {
                    "confidence": "deterministic",
                    "evidenceSource": ["board_rules"],
                },
                "analysis": {
                    "source": "katago", "demo": False, "winrate": 52.0,
                    "scoreLead": 1.0, "bestMove": "Q9", "visits": 800,
                },
                "heuristics": {"confidence": "heuristic"},
                "moveCandidates": {
                    "sameMove": (variation[-1] if variation else "L11") == "Q9",
                    "actual": {
                        "move": variation[-1] if variation else "L11",
                        "region": {"label": "右边中腹"},
                        "heuristics": {"role": "实战手局部作用"},
                    },
                    "best": {
                        "move": "Q9",
                        "region": {"label": "右边中腹"},
                        "heuristics": {"role": "AI 首选局部作用"},
                    },
                },
            },
            "expression": {
                "baselinePurpose": {"confidence": "heuristic"},
            },
            "provenance": [
                {
                    "type": "rule", "source": "goboard.py",
                    "confidence": "deterministic",
                },
                {
                    "type": "katago", "source": "katago",
                    "backend": "OpenCL", "visits": 800, "demo": False,
                },
                {
                    "type": "heuristic", "source": "reports.py",
                    "confidence": "heuristic",
                },
            ],
        }

    def explain_route(route):
        body = route.request.post_data_json
        explain_payloads.append(body)
        context = teaching_context(body)
        primary = {
            "source": "baseline", "sourceLabel": "基础棋理", "latencyMs": 0,
            "title": "服务端权威讲解",
            "paragraphs": ["规则事实、KataGo事实和启发式判断已在服务端重建。"],
        }
        route.fulfill(json={
            "mode": body.get("mode", "baseline"),
            "primary": primary, "results": {"baseline": primary},
            "degraded": False,
            "evidence": context["facts"]["analysis"],
            "evidenceLine": f"第 {context['subject']['effectiveTurn']} 手，KataGo 权威证据。",
            "teachingContext": context,
        })

    def chat_route(route):
        body = route.request.post_data_json
        chat_payloads.append(body)
        context = teaching_context(body)
        target_kind = body.get("targetKind") or "actual"
        target_move = (
            context["facts"]["moveCandidates"].get(target_kind, {}).get("move")
        )
        route.fulfill(json={
            "answer": "这条回答只使用服务端重建的当前变化证据。",
            "followUps": [], "source": "baseline",
            "sourceLabel": "基础棋理解答", "latencyMs": 0,
            "degraded": True, "actions": [],
            "context": {
                "turn": context["subject"]["effectiveTurn"],
                "move": context["subject"]["move"],
                "evidenceLine": "KataGo 权威证据",
                "gameId": context["gameId"],
                "contextId": context["contextId"],
                "positionHash": context["positionHash"],
                "baseTurn": context["subject"]["baseTurn"],
                "variation": context["subject"]["variation"],
                "questionTarget": {
                    "kind": target_kind,
                    "label": "AI 首选" if target_kind == "best" else "实战手",
                    "move": target_move,
                    "source": "client_intent_server_resolved",
                    "confidence": "high",
                    "evidencePath": f"facts.moveCandidates.{target_kind}",
                },
            },
            "teachingContext": context,
        })

    def feedback_route(route):
        feedback_payloads.append(route.request.post_data_json)
        route.fulfill(json={"saved": True, "id": "feedback-authority"})

    page.route("**/api/mentor/explain", explain_route)
    page.route("**/api/mentor/chat", chat_route)
    page.route("**/api/mentor/feedback", feedback_route)
    page.evaluate("""() => {
      S.currentLibraryId = "authority-game";
      S.reportId = "authority-report";
      S.reportRevision = "revision-authority";
      S.mentorCache.clear();
      clearExploration(false);
      setPos(0);
    }""")
    # 后台讲解故意延后 1.2 秒，给用户显式问棋让出单并发模型槽位。
    page.wait_for_timeout(1500)
    check("开局前讲解同样由服务端权威重建",
          bool(explain_payloads)
          and explain_payloads[-1]["turn"] == 0
          and explain_payloads[-1]["variation"] == [],
          str(explain_payloads[-1] if explain_payloads else {}))
    page.evaluate("""() => {
      S.currentLibraryId = "authority-game";
      S.reportId = "authority-report";
      S.reportRevision = "revision-authority";
      S.mentorCache.clear();
      clearExploration(false);
      setPos(78);
    }""")
    page.wait_for_timeout(1500)
    check("主线讲解只提交服务端定位符",
          bool(explain_payloads)
          and set(explain_payloads[-1]) ==
              {"gameId", "reportId", "turn", "variation", "mode"}
          and explain_payloads[-1]["turn"] == 78
          and explain_payloads[-1]["variation"] == [],
          str(explain_payloads[-1] if explain_payloads else {}))
    check("服务端权威上下文成功驱动基础讲解",
          "服务端权威讲解" in page.text_content("#roleExplanation")
          and "KataGo 权威证据" in page.text_content("#coachMsg"))
    check("权威响应显示真实 KataGo 徽标",
          page.text_content("#coachAuthorityBadge").strip() == "真实 KataGo",
          page.text_content("#coachAuthorityBadge"))
    rules_evidence_text = page.text_content('[data-testid="evidence-rules"]')
    katago_evidence_text = page.text_content('[data-testid="evidence-katago"]')
    heuristic_evidence_text = page.text_content(
        '[data-testid="evidence-heuristic"]')
    expression_evidence_text = page.text_content(
        '[data-testid="evidence-expression"]')
    check("规则证据显示服务端确定性",
          "规则" in rules_evidence_text and "服务端确定" in rules_evidence_text,
          rules_evidence_text)
    check("KataGo 证据显示真实搜索预算",
          "KataGo" in katago_evidence_text
          and "800 visits" in katago_evidence_text,
          katago_evidence_text)
    check("启发式证据明确需要变化验证",
          "启发式" in heuristic_evidence_text
          and "需变化验证" in heuristic_evidence_text,
          heuristic_evidence_text)
    check("表达层明确为确定性基础讲解",
          "基础讲解" in expression_evidence_text
          and "确定性表达" in expression_evidence_text,
          expression_evidence_text)
    if not page.locator('[data-testid="evidence-panel"]').is_visible():
        page.click('[data-testid="agent-evidence-toggle"]')
    page.click('[data-testid="evidence-katago"]')
    analysis_evidence_detail = page.text_content("#evidenceDetail")
    check("KataGo 证据详情明确黑方视角与胜率",
          page.locator("#evidenceDetail").is_visible()
          and "黑方视角" in analysis_evidence_detail
          and "黑方胜率 52.0%" in analysis_evidence_detail,
          analysis_evidence_detail)
    page.click("#evidenceReceiptButton")
    check("证据回执弹窗打开",
          page.locator("#trustDialog").is_visible()
          and page.locator('[data-testid="evidence-receipt"]').is_visible())
    receipt_text = page.text_content('[data-testid="evidence-receipt"]')
    check("证据回执显示上下文、修订与证据指纹",
          "Context" in receipt_text
          and "ctx-authority-game" in receipt_text
          and "报告修订" in receipt_text
          and "revision-authority" in receipt_text
          and "证据指纹" in receipt_text
          and "evidence-authority" in receipt_text,
          receipt_text)
    check("证据回执显示三类来源与 OpenCL 实测信息",
          all(
              text in receipt_text
              for text in (
                  "规则事实", "KataGo 分析", "启发式判断",
                  "OpenCL", "800 visits",
              )
          ),
          receipt_text)
    check("OpenCL 权威回执不会冒充 ROCm",
          "ROCm" not in receipt_text, receipt_text)
    page.click("#trustClose")
    check("证据回执可关闭", not page.locator("#trustDialog").is_visible())
    page.evaluate("setPos(S.cur)")
    check("同一手二次渲染不会把已完成证据改回加载态",
          "KataGo 权威证据" in page.text_content("#coachMsg")
          and "正在由服务端重建" not in page.text_content("#coachMsg"))
    check("真实证据脚注只在服务端确认后标为 KataGo",
          "当前精确数值来自真实 KataGo"
          in page.text_content("#mentorQaFoot"))

    page.click("#aiMoveTag")
    page.wait_for_timeout(500)
    check("变化讲解提交基准手和当前可见前缀",
          explain_payloads[-1]["turn"] == 77
          and explain_payloads[-1]["variation"] == ["Q9"],
          str(explain_payloads[-1]))
    variation_ui_before = page.evaluate("""() => ({
      cur:S.cur,
      baseTurn:S.variation?.baseTurn,
      step:S.variation?.step,
      visibleMoves:variationGtpMoves(),
      source:S.variation?.source,
      returnTurn:S.comparisonReturnTurn,
      parentCount:S.variationParents.length,
      boardMode:boardModeChip.textContent,
    })""")
    page.click('[data-testid="agent-evidence-toggle"]')
    page.click("#agentToolsClose")
    variation_ui_after = page.evaluate("""() => ({
      cur:S.cur,
      baseTurn:S.variation?.baseTurn,
      step:S.variation?.step,
      visibleMoves:variationGtpMoves(),
      source:S.variation?.source,
      returnTurn:S.comparisonReturnTurn,
      parentCount:S.variationParents.length,
      boardMode:boardModeChip.textContent,
    })""")
    check("开合证据工具不改变 AI 变化状态",
          variation_ui_after == variation_ui_before,
          f"before={variation_ui_before}, after={variation_ui_after}")
    page.set_viewport_size({"width": 1280, "height": 720})
    page.evaluate("focusReviewWorkspace()")
    page.evaluate("""() => {
      const nativeFetch = window.fetch.bind(window);
      window.fetch = (input, init = {}) => {
        const url = typeof input === "string" ? input : input.url;
        let body = {};
        try { body = JSON.parse(init.body || "{}"); } catch (_) {}
        if (url === "/api/mentor/chat" &&
            body.question === "为什么这条变化更好？") {
          return new Promise((resolve, reject) => {
            setTimeout(() => nativeFetch(input, init).then(resolve, reject), 2200);
          });
        }
        return nativeFetch(input, init);
      };
    }""")
    page.fill("#mentorQaInput", "为什么这条变化更好？")
    page.click("#mentorQaSend")
    page.wait_for_timeout(150)
    thinking_box = page.locator('[data-testid="qa-thinking-card"]').bounding_box()
    messages_box = page.locator("#mentorQaMessages").bounding_box()
    check("真实慢请求会立即显示视口内等待控制条",
          thinking_box is not None and messages_box is not None
          and 55 <= thinking_box["height"] <= messages_box["height"]
          and thinking_box["y"] >= messages_box["y"]
          and thinking_box["y"] + thinking_box["height"]
          <= messages_box["y"] + messages_box["height"] + 1
          and page.locator(".qa-thinking-cancel").is_visible(),
          f"等待卡={thinking_box}, 消息区={messages_box}")
    page.wait_for_timeout(1100)
    check("真实慢请求显示实际等待时间",
          "已等待 1 秒" in
          page.text_content('[data-testid="qa-thinking-card"]'))
    page.screenshot(path=os.path.join(OUT, "工作台-问棋等待态.png"))
    page.set_viewport_size({"width": 1600, "height": 900})
    page.wait_for_timeout(1200)
    check("真实慢请求完成后等待控制条自动消失",
          page.locator('[data-testid="qa-thinking-card"]').count() == 0
          and not page.locator("#mentorQaSend").is_disabled())
    check("问棋请求不再携带客户端事实",
          bool(chat_payloads)
          and set(chat_payloads[-1]) == {
              "gameId", "reportId", "turn", "variation",
              "question", "provider", "targetKind", "history",
          }
          and chat_payloads[-1]["turn"] == 77
          and chat_payloads[-1]["variation"] == ["Q9"],
          str(chat_payloads[-1] if chat_payloads else {}))
    check("问棋回答绑定服务端 contextId",
          "服务端重建" in page.text_content("#mentorQaMessages")
          and page.evaluate(
              "S.qaMessages.at(-1)?.contextId === "
              "S.mentorResult?.teachingContext?.contextId"))
    page.fill("#mentorQaInput", "那我下一步该注意什么？")
    page.click("#mentorQaSend")
    page.wait_for_timeout(250)
    check("同一权威上下文的第二问会携带已绑定历史",
          len(chat_payloads) >= 2
          and len(chat_payloads[-1].get("history", [])) >= 2
          and all(
              item.get("contextId") == teaching_context(chat_payloads[-1])["contextId"]
              for item in chat_payloads[-1]["history"]
          ),
          str(chat_payloads[-1] if chat_payloads else {}))
    if not page.locator('[data-testid="evidence-panel"]').is_visible():
        page.click('[data-testid="agent-evidence-toggle"]')
    if not page.locator("#mentorFeedback").is_visible():
        page.click(".agent-feedback-disclosure summary")
    page.click('[data-mentor-feedback="helpful"]')
    page.wait_for_timeout(100)
    check("讲解反馈携带权威上下文标识",
          bool(feedback_payloads)
          and feedback_payloads[-1]["contextId"].startswith("ctx-")
          and feedback_payloads[-1]["positionHash"].startswith("hash-"),
          str(feedback_payloads[-1] if feedback_payloads else {}))
    check("反馈同时携带服务端定位符",
          feedback_payloads[-1]["reportId"] == "authority-report"
          and feedback_payloads[-1]["turn"] == 77
          and feedback_payloads[-1]["variation"] == ["Q9"],
          str(feedback_payloads[-1] if feedback_payloads else {}))

    check("交互后控制台零报错", not errors, "; ".join(errors[:3]))
    page.close()

    # ---- file:// 无后端回退 ----
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///" + WEB_FILE.replace("\\", "/"))
    page.wait_for_timeout(800)
    chip = page.text_content("#engineChip")
    check("file:// 回退本地演示", "后端未连接" in chip, chip)
    check("file:// 棋局载入", "180" in page.text_content("#gameInfo"))
    # fetch 失败本身会打一条 console error，属预期；过滤后应无其他错误
    real_errors = [e for e in errors if "Failed to fetch" not in e
                   and "ERR_FILE_NOT_FOUND" not in e and "/api/demo" not in e
                   and "/api/health" not in e]
    check("file:// 无脚本错误", not real_errors, "; ".join(real_errors[:3]))
    page.screenshot(path=os.path.join(OUT, "工作台-file回退.png"))
    page.close()
    browser.close()

print()
if failures:
    print(f"共 {len(failures)} 项失败：", failures)
    sys.exit(1)
print("=== UI 验证全部通过 ===")
