#include "robot_renderer.h"
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <windows.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

// EVE palette
static const D2D1::ColorF C_WHITE       (0xFFFCFCFC);
static const D2D1::ColorF C_WHITE_LIGHT (0xFFFFFFFF);
static const D2D1::ColorF C_WHITE_SHADE (0xFFE4E4E4);
static const D2D1::ColorF C_WHITE_MID   (0xFFF1F1F1);
static const D2D1::ColorF C_BLACK       (0xFF141414);
static const D2D1::ColorF C_NEON        (0xFF00CFFF); // sharp neon blue (no soft glow)
static const D2D1::ColorF C_NEON_BRIGHT (0xFF7CF0FF);
static const D2D1::ColorF C_NEON_DIM    (0xFF006E8C);
static const D2D1::ColorF C_PLANT       (0xFF00FF66);
static const D2D1::ColorF C_SHADOW      (0xFFEFEFEF);
static const D2D1::ColorF C_GLOW        (0xFFCFF0FF);
static const D2D1::ColorF C_CAPE        (0xFFE00000); // pure red cape
static const D2D1::ColorF C_CAPE_SHADE  (0xFF990000); // dark red for shading
static const D2D1::ColorF C_CREST       (0xFFFFC125); // Spartan crest gold
static const D2D1::ColorF C_GOLD        (0xFFDAA520); // golden armor body
static const D2D1::ColorF C_GOLD_LIGHT  (0xFFFFE4B5); // light gold highlight
static const D2D1::ColorF C_GOLD_DARK   (0xFF8B6914); // dark gold shade
static const D2D1::ColorF C_GOLD_MID    (0xFFC49A34); // mid gold
static const D2D1::ColorF C_GREEN       (0xFF39FF14); // bright neon green eyes
static const D2D1::ColorF C_GREEN_LIGHT (0xFF7FFF00); // yellow-green eye core
static const D2D1::ColorF C_ELECTRIC    (0xFF00FFFF); // cyan electric arc

static float GetIdleDuration() {
    return 25.0f + (float)(rand() % 10);
}

static inline float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }
static inline float EaseOutQuad(float t) { return 1.0f - (1.0f - t) * (1.0f - t); }
static inline float SmoothStep(float t) { return t * t * (3.0f - 2.0f * t); }

// Builds a heater-shield body path: flat-ish top, curving sides, pointed bottom.
// Shield dimensions: ~64 wide (-32..32), ~98 tall (-44..54).
static void FillShieldBodyPath(ID2D1Factory* factory, ID2D1RenderTarget* target,
                                float cx, float centerY, float scale,
                                float offsetX, float offsetY, ID2D1Brush* brush) {
    ComPtr<ID2D1PathGeometry> geo;
    factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + offsetX + x * scale, centerY + offsetY + y * scale);
    };

    // Shield outline: flat top with slight dip, curving sides to a point
    sink->BeginFigure(pt(-32, -44), D2D1_FIGURE_BEGIN_FILLED);
    // Top edge — slight curve down in middle for character
    sink->AddBezier(D2D1::BezierSegment(pt(-10, -41), pt(10, -41), pt(32, -44)));
    // Right side curving down and inward
    sink->AddBezier(D2D1::BezierSegment(pt(34, -20), pt(30, 10), pt(20, 30)));
    // Bottom right to point
    sink->AddBezier(D2D1::BezierSegment(pt(12, 42), pt(4, 52), pt(0, 54)));
    // Bottom left from point
    sink->AddBezier(D2D1::BezierSegment(pt(-4, 52), pt(-12, 42), pt(-20, 30)));
    // Left side curving back up
    sink->AddBezier(D2D1::BezierSegment(pt(-30, 10), pt(-34, -20), pt(-32, -44)));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();

    target->FillGeometry(geo.Get(), brush);
}

// Stroke version — draws an outline around the shield body path
static void StrokeShieldBodyPath(ID2D1Factory* factory, ID2D1RenderTarget* target,
                                  float cx, float centerY, float scale,
                                  float offsetX, float offsetY, ID2D1Brush* brush, float strokeWidth) {
    ComPtr<ID2D1PathGeometry> geo;
    factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + offsetX + x * scale, centerY + offsetY + y * scale);
    };

    sink->BeginFigure(pt(-32, -44), D2D1_FIGURE_BEGIN_FILLED);
    sink->AddBezier(D2D1::BezierSegment(pt(-10, -41), pt(10, -41), pt(32, -44)));
    sink->AddBezier(D2D1::BezierSegment(pt(34, -20), pt(30, 10), pt(20, 30)));
    sink->AddBezier(D2D1::BezierSegment(pt(12, 42), pt(4, 52), pt(0, 54)));
    sink->AddBezier(D2D1::BezierSegment(pt(-4, 52), pt(-12, 42), pt(-20, 30)));
    sink->AddBezier(D2D1::BezierSegment(pt(-30, 10), pt(-34, -20), pt(-32, -44)));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();

    target->DrawGeometry(geo.Get(), brush, strokeWidth);
}

// Spartan / Corinthian helmet path: domed crown, wide cheek guards,
// pointed nose guard, and a tapered chin. Dimensions ~56 wide, ~50 tall.
static void FillHelmetPath(ID2D1Factory* factory, ID2D1RenderTarget* target,
                           float cx, float headY, float scale,
                           float offsetX, float offsetY, ID2D1Brush* brush) {
    ComPtr<ID2D1PathGeometry> geo;
    factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + offsetX + x * scale, headY + offsetY + y * scale);
    };

    // Corinthian helmet outline
    sink->BeginFigure(pt(-28, 8), D2D1_FIGURE_BEGIN_FILLED);
    // Left cheek guard curve
    sink->AddBezier(D2D1::BezierSegment(pt(-30, -5), pt(-26, -15), pt(-20, -22)));
    // Left dome up to crown
    sink->AddBezier(D2D1::BezierSegment(pt(-12, -28), pt(-6, -30), pt(0, -30)));
    // Right dome down
    sink->AddBezier(D2D1::BezierSegment(pt(6, -30), pt(12, -28), pt(20, -22)));
    // Right cheek guard curve
    sink->AddBezier(D2D1::BezierSegment(pt(26, -15), pt(30, -5), pt(28, 8)));
    // Right side down to chin
    sink->AddLine(pt(24, 18));
    // Chin taper with slight point
    sink->AddBezier(D2D1::BezierSegment(pt(18, 24), pt(-18, 24), pt(-24, 18)));
    // Left side back up
    sink->AddLine(pt(-28, 8));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();

    target->FillGeometry(geo.Get(), brush);
}

// Stroke version of Spartan helmet path
static void StrokeHelmetPath(ID2D1Factory* factory, ID2D1RenderTarget* target,
                             float cx, float headY, float scale,
                             float offsetX, float offsetY, ID2D1Brush* brush, float strokeWidth) {
    ComPtr<ID2D1PathGeometry> geo;
    factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + offsetX + x * scale, headY + offsetY + y * scale);
    };

    sink->BeginFigure(pt(-28, 8), D2D1_FIGURE_BEGIN_FILLED);
    sink->AddBezier(D2D1::BezierSegment(pt(-30, -5), pt(-26, -15), pt(-20, -22)));
    sink->AddBezier(D2D1::BezierSegment(pt(-12, -28), pt(-6, -30), pt(0, -30)));
    sink->AddBezier(D2D1::BezierSegment(pt(6, -30), pt(12, -28), pt(20, -22)));
    sink->AddBezier(D2D1::BezierSegment(pt(26, -15), pt(30, -5), pt(28, 8)));
    sink->AddLine(pt(24, 18));
    sink->AddBezier(D2D1::BezierSegment(pt(18, 24), pt(-18, 24), pt(-24, 18)));
    sink->AddLine(pt(-28, 8));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();

    target->DrawGeometry(geo.Get(), brush, strokeWidth);
}

RobotRenderer::RobotRenderer() {
    srand((unsigned)time(nullptr));
    memset(m_lastKeyState, 0, sizeof(m_lastKeyState));
}

RobotRenderer::~RobotRenderer() {
    if (m_target) m_target->Release();
}

bool RobotRenderer::Initialize(HWND hwnd) {
    m_hwnd = hwnd;
    HRESULT hr = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, m_factory.GetAddressOf());
    if (FAILED(hr)) return false;

    RECT rc;
    GetClientRect(hwnd, &rc);
    D2D1_SIZE_U size = D2D1::SizeU(rc.right - rc.left, rc.bottom - rc.top);

    hr = m_factory->CreateHwndRenderTarget(
        D2D1::RenderTargetProperties(),
        D2D1::HwndRenderTargetProperties(hwnd, size, D2D1_PRESENT_OPTIONS_IMMEDIATELY),
        m_target.GetAddressOf()
    );
    if (FAILED(hr)) return false;

    // Color-key transparency needs hard (non-anti-aliased) edges, otherwise
    // blended pixels against magenta show up as a pink/purple fringe.
    m_target->SetAntialiasMode(D2D1_ANTIALIAS_MODE_ALIASED);

    m_target->CreateSolidColorBrush(C_WHITE,       m_brushWhite.GetAddressOf());
    m_target->CreateSolidColorBrush(C_WHITE_LIGHT, m_brushWhiteLight.GetAddressOf());
    m_target->CreateSolidColorBrush(C_WHITE_SHADE, m_brushWhiteShade.GetAddressOf());
    m_target->CreateSolidColorBrush(C_WHITE_MID,   m_brushWhiteMid.GetAddressOf());
    m_target->CreateSolidColorBrush(C_BLACK,       m_brushBlack.GetAddressOf());
    m_target->CreateSolidColorBrush(C_NEON,        m_brushNeon.GetAddressOf());
    m_target->CreateSolidColorBrush(C_NEON_BRIGHT, m_brushNeonBright.GetAddressOf());
    m_target->CreateSolidColorBrush(C_NEON_DIM,    m_brushNeonDim.GetAddressOf());
    m_target->CreateSolidColorBrush(C_PLANT,       m_brushPlant.GetAddressOf());
    m_target->CreateSolidColorBrush(C_SHADOW,      m_brushShadow.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GLOW,        m_brushGlow.GetAddressOf());
    m_target->CreateSolidColorBrush(C_WHITE_LIGHT, m_brushSpark.GetAddressOf());
    m_target->CreateSolidColorBrush(D2D1::ColorF(0xFF222222), m_brushOutline.GetAddressOf());
    m_target->CreateSolidColorBrush(C_CAPE,        m_brushCape.GetAddressOf());
    m_target->CreateSolidColorBrush(C_CAPE_SHADE,  m_brushCapeShade.GetAddressOf());
    m_target->CreateSolidColorBrush(C_CREST,       m_brushCrest.GetAddressOf());
    m_target->CreateSolidColorBrush(C_ELECTRIC,    m_brushElectric.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GREEN,       m_brushGreen.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GREEN_LIGHT, m_brushGreenBright.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GOLD,        m_brushGold.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GOLD_LIGHT,  m_brushGoldLight.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GOLD_DARK,   m_brushGoldDark.GetAddressOf());
    m_target->CreateSolidColorBrush(C_GOLD_MID,    m_brushGoldMid.GetAddressOf());

    // Initialize to gold armor color scheme immediately
    UpdateColorScheme();

    return true;
}

void RobotRenderer::OnResize(int width, int height) {
    if (m_target) m_target->Resize(D2D1::SizeU(width, height));
}

// ── Screen edges ─────────────────────────────────────────────────────

float RobotRenderer::GetScreenLeftEdge() { return 10.0f; }

float RobotRenderer::GetScreenRightEdge() {
    RECT workArea;
    SystemParametersInfo(SPI_GETWORKAREA, 0, &workArea, 0);
    return (float)(workArea.right - 230);
}

void RobotRenderer::WalkToEdge(bool left) {
    m_targetX = left ? GetScreenLeftEdge() : GetScreenRightEdge();
    m_facingRight = !left;
    m_userWalking = true;
    SetState(RobotState::Walking, 999.0f);
}

void RobotRenderer::StartSpinThenWalk(bool left) {
    m_spinWalkLeft = left;
    m_spinTimer = 0.0f;
    m_targetX = left ? GetScreenLeftEdge() : GetScreenRightEdge();
    m_facingRight = !left;
    SetState(RobotState::Spinning, m_spinDuration);
}

// ── Keyboard detection ───────────────────────────────────────────────

void RobotRenderer::CheckKeyboardActivity() {
    m_keyboardCheckTimer += 0.016f;
    if (m_keyboardCheckTimer < 0.3f) return;
    m_keyboardCheckTimer = 0.0f;

    HWND fgWnd = GetForegroundWindow();
    if (fgWnd != m_lastForegroundWnd && m_lastForegroundWnd != nullptr) {
        float le = GetScreenLeftEdge(), re = GetScreenRightEdge();
        float ms = le + (re - le) / 3.0f, me = le + 2.0f * (re - le) / 3.0f;
        if (m_screenX > ms && m_screenX < me) {
            StartSpinThenWalk(m_screenX < (le + re) / 2.0f);
            m_typingCooldown = 30.0f;
        }
    }
    m_lastForegroundWnd = fgWnd;

    bool anyKey = false;
    for (int vk = 0x08; vk <= 0x5A; vk++) {
        bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
        if (down && !m_lastKeyState[vk]) anyKey = true;
        m_lastKeyState[vk] = down;
    }
    for (int vk : {0x20, 0x0D}) {
        bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
        if (down && !m_lastKeyState[vk]) anyKey = true;
        m_lastKeyState[vk] = down;
    }

    if (anyKey && m_typingCooldown <= 0) {
        float le = GetScreenLeftEdge(), re = GetScreenRightEdge();
        float ms = le + (re - le) / 3.0f, me = le + 2.0f * (re - le) / 3.0f;
        if (m_screenX > ms && m_screenX < me) {
            StartSpinThenWalk(m_screenX < (le + re) / 2.0f);
            m_typingCooldown = 30.0f;
        }
    }
}

// ── Mouse interaction ────────────────────────────────────────────────

void RobotRenderer::OnMouseDown(int mouseX, int mouseY) {
    m_mouseDown = true;
    m_dragging = false;
    m_holdTimer = 0.0f;
    m_downX = mouseX;
    m_downY = mouseY;
    m_dragStartX = m_screenX;
    m_dragStartY = m_screenY;
    // Store screen coords for accurate drag tracking across window moves
    POINT pt = {mouseX, mouseY};
    if (m_hwnd) ClientToScreen(m_hwnd, &pt);
    m_downScreenX = pt.x;
    m_downScreenY = pt.y;
}

void RobotRenderer::OnMouseMove(int mouseX, int mouseY) {
    if (!m_mouseDown) return;
    // Use screen coordinates so drag delta stays correct even when
    // the window itself moves during dragging.
    POINT pt = {mouseX, mouseY};
    if (m_hwnd) ClientToScreen(m_hwnd, &pt);
    float dx = (float)(pt.x - m_downScreenX);
    float dy = (float)(pt.y - m_downScreenY);
    m_holdTimer += 0.016f;
    if (!m_dragging && (m_holdTimer > 0.25f || dx * dx + dy * dy > 81.0f)) {
        m_dragging = true;
        SetState(RobotState::Idle, 999.0f);
    }
    if (m_dragging) {
        m_screenX = m_dragStartX + dx;
        m_screenY = m_dragStartY - dy;
        MoveWindowToRobot();
    }
}

void RobotRenderer::OnMouseUp(int mouseX, int mouseY) {
    if (m_dragging) {
        m_dragging = false;
        m_mouseDown = false;
        SetState(RobotState::Idle, GetIdleDuration());
        return;
    }
    if (m_mouseDown) {
        m_mouseDown = false;
        ClickRegion region = HitTest(mouseX, mouseY);
        switch (region) {
            case ClickRegion::Head:
                m_wantsInputDialog = true;
                // Don't lock in Working state — let robot keep moving
                SetState(RobotState::Idle, GetIdleDuration());
                break;
            case ClickRegion::Arms:
                SetState(RobotState::Greeting, 2.0f);
                break;
            case ClickRegion::Bottom: {
                float center = (GetScreenLeftEdge() + GetScreenRightEdge()) / 2.0f;
                StartSpinThenWalk(m_screenX >= center);
                break;
            }
            default:
                SetState(RobotState::Greeting, 1.8f);
                break;
        }
    }
}

ClickRegion RobotRenderer::HitTest(int mouseX, int mouseY) {
    if (!m_target) return ClickRegion::None;
    D2D1_SIZE_F size = m_target->GetSize();
    float cx = size.width / 2;
    float cy = size.height / 2;
    float fx = (float)mouseX;
    float fy = (float)mouseY;

    if (fy < cy - 46) return ClickRegion::Head;
    if (fy > cy + 30) return ClickRegion::Bottom;
    if (fx < cx - 33 || fx > cx + 33) return ClickRegion::Arms;
    return ClickRegion::None;
}

// ── State machine ────────────────────────────────────────────────────

void RobotRenderer::SetState(RobotState state, float duration) {
    m_state = state;
    m_stateTimer = 0.0f;
    m_nextBehaviorTime = duration;
}

void RobotRenderer::PickNextBehavior() {
    float roll = (float)rand() / RAND_MAX;
    if (roll < 0.15f) {
        SetState(RobotState::Greeting, 1.5f);
    } else if (roll < 0.85f) {
        m_userWalking = false;
        StartSpinThenWalk(rand() % 2 == 0);
    } else {
        SetState(RobotState::Sleeping, 15.0f);
    }
}

void RobotRenderer::MoveWindowToRobot() {
    if (!m_hwnd) return;
    RECT workArea;
    SystemParametersInfo(SPI_GETWORKAREA, 0, &workArea, 0);
    int winW = 220, winH = 220;
    int x = (int)m_screenX;
    int y = workArea.bottom - winH - 10 - (int)m_screenY;
    if (x < 0) x = 0;
    if (x + winW > workArea.right) x = workArea.right - winW;
    if (y < workArea.top) y = workArea.top;
    SetWindowPos(m_hwnd, HWND_TOPMOST, x, y, winW, winH,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
}

// Dynamic lean: a quick "launch" dash up toward a steep angle, settling to
// a lower cruising lean, then easing back upright as EVE nears her target.
float RobotRenderer::ComputeWalkLeanDeg() const {
    float distToTarget = fabsf(m_targetX - m_screenX);
    const float peakLean = 75.0f;
    const float cruiseLean = 26.0f;
    const float rampDur = 0.18f;
    const float settleDur = 0.28f;

    float lean;
    if (m_stateTimer < rampDur) {
        lean = peakLean * EaseOutQuad(Clamp01(m_stateTimer / rampDur));
    } else {
        float t = Clamp01((m_stateTimer - rampDur) / settleDur);
        lean = peakLean + (cruiseLean - peakLean) * SmoothStep(t);
    }

    const float arrivalDist = 55.0f;
    float arrivalFactor = Clamp01(distToTarget / arrivalDist);
    lean *= arrivalFactor;

    return lean * (m_facingRight ? 1.0f : -1.0f);
}

void RobotRenderer::Update() {
    float dt = 0.016f;
    m_animTime += dt;
    m_stateTimer += dt;
    if (m_typingCooldown > 0) m_typingCooldown -= dt;

    // Check background brightness every ~0.5s for adaptive coloring
    m_bgCheckTimer += dt;
    if (m_bgCheckTimer >= 0.5f) {
        m_bgCheckTimer = 0.0f;
        SampleBackgroundBrightness();
    }

    // Cycle idle eye expressions so EVE feels alive, not a static stare.
    if (m_state == RobotState::Idle && !m_dragging) {
        m_eyeExprTimer -= dt;
        if (m_eyeExprTimer <= 0.0f) {
            static const EyeExpression pool[] = {
                EyeExpression::Neutral, EyeExpression::Happy, EyeExpression::Curious,
                EyeExpression::Surprised, EyeExpression::Wink, EyeExpression::Suspicious
            };
            m_eyeExpression = pool[rand() % 6];
            m_eyeExprTimer = 6.0f + (float)(rand() % 7);
        }
    }

    if (m_state != RobotState::Working && m_state != RobotState::Walking &&
        m_state != RobotState::Spinning && !m_dragging)
        CheckKeyboardActivity();
    if (m_state == RobotState::Spinning && !m_dragging) {
        m_spinTimer += dt;
        if (m_spinTimer >= m_spinDuration) {
            m_userWalking = true;
            SetState(RobotState::Walking, 999.0f);
        }
    }
    if (m_state == RobotState::Walking && !m_dragging) {
        float dx = m_targetX - m_screenX;
        if (fabs(dx) < 3.0f) {
            m_screenX = m_targetX;
            m_userWalking = false;
            SetState(RobotState::Idle, GetIdleDuration());
        } else {
            float step = m_hoverSpeed * dt;
            if (fabs(dx) < step) step = fabs(dx);
            if (dx > 0) { m_screenX += step; m_facingRight = true; }
            else { m_screenX -= step; m_facingRight = false; }
        }
        MoveWindowToRobot();
    }
    if (!m_dragging && m_stateTimer >= m_nextBehaviorTime) {
        if (m_state == RobotState::Working || m_state == RobotState::Greeting)
            SetState(RobotState::Idle, GetIdleDuration());
        else if (m_state == RobotState::Spinning) {
            // Spin finished — transition to walking handled above
        }
        else if (m_state == RobotState::Walking) {
            if (fabs(m_targetX - m_screenX) < 3.0f)
                SetState(RobotState::Idle, GetIdleDuration());
        } else
            PickNextBehavior();
    }
}

void RobotRenderer::Render() {
    if (!m_target) return;
    m_target->BeginDraw();
    m_target->Clear(D2D1::ColorF(D2D1::ColorF::Magenta, 1.0f));
    DrawRobot();
    m_target->EndDraw();
}

// ── Drawing ───────────────────────────────────────────────────────────

void RobotRenderer::DrawGroundShadow(float cx, float baseY, float w) {
    D2D1_ELLIPSE ell = D2D1::Ellipse(D2D1::Point2F(cx, baseY), w / 2, w / 10);
    m_target->FillEllipse(ell, m_brushShadow.Get());
}

void RobotRenderer::DrawHoverGlow(float cx, float baseY) {
    float pulse = 0.85f + 0.15f * sinf(m_animTime * 3.0f * (float)M_PI);
    float r = 20 * pulse;
    D2D1_ELLIPSE glow = D2D1::Ellipse(D2D1::Point2F(cx, baseY), r, r * 0.32f);
    m_target->FillEllipse(glow, m_brushGlow.Get());
}

// ── Adaptive color scheme ─────────────────────────────────────────────
// Samples screen pixels around the robot to detect bright backgrounds.
// When background is bright, body switches to dark for visibility.

void RobotRenderer::SampleBackgroundBrightness() {
    if (!m_hwnd) return;

    RECT rc;
    GetWindowRect(m_hwnd, &rc);
    int cx = (rc.left + rc.right) / 2;
    int cy = (rc.top + rc.bottom) / 2;

    HDC screenDC = GetDC(nullptr);
    if (!screenDC) return;

    // Sample 5 points around (not under) the robot window
    int offsets[][2] = {
        { -130,    0 }, { 130,    0 },
        {    0, -110 }, {   0,  110 },
        {  -90,   90 },
    };
    int totalLum = 0;
    int count = 0;
    for (auto& off : offsets) {
        int px = cx + off[0];
        int py = cy + off[1];
        // Skip if off-screen
        if (px < 0 || py < 0) continue;
        COLORREF c = GetPixel(screenDC, px, py);
        int r = GetRValue(c), g = GetGValue(c), b = GetBValue(c);
        // Perceived luminance (Rec. 601 weighting)
        totalLum += (r * 299 + g * 587 + b * 114) / 1000;
        count++;
    }
    ReleaseDC(nullptr, screenDC);

    if (count == 0) return;
    int avgLum = totalLum / count;
    bool shouldBeDark = (avgLum > 160);

    if (shouldBeDark != m_darkMode) {
        m_darkMode = shouldBeDark;
        UpdateColorScheme();
    }
}

void RobotRenderer::UpdateColorScheme() {
    // Always use golden armor palette
    m_brushWhite->SetColor(C_GOLD);
    m_brushWhiteLight->SetColor(C_GOLD_LIGHT);
    m_brushWhiteShade->SetColor(C_GOLD_DARK);
    m_brushWhiteMid->SetColor(C_GOLD_MID);
    m_brushShadow->SetColor(D2D1::ColorF(0x44000000));
    m_brushGlow->SetColor(D2D1::ColorF(0xFFCFF0FF));
}

void RobotRenderer::DrawEggBody(float cx, float cy, float bob) {
    float centerY = cy + bob;

    // Shield body — layered fills for depth (same technique as egg, new shape)
    // 1. Shadow offset layer
    FillShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 1.03f, 2.0f, 2.0f, m_brushWhiteShade.Get());
    // 2. Main white body
    FillShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 1.0f, 0.0f, 0.0f, m_brushWhite.Get());
    // 3. Mid-tone right side shading
    FillShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 0.90f, 9.0f, 0.0f, m_brushWhiteMid.Get());
    // 4. Deeper shade right edge
    FillShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 0.76f, 13.0f, 0.0f, m_brushWhiteShade.Get());
    // 5. Blend back left side to white
    FillShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 0.92f, -4.0f, 0.0f, m_brushWhite.Get());

    // Shield-specific details:
    // Neon blue rim outline (thin, sharp)
    StrokeShieldBodyPath(m_factory.Get(), m_target.Get(), cx, centerY, 1.0f, 0.0f, 0.0f,
                         m_brushNeon.Get(), 1.5f);

    // Center ridge line (vertical, from top to bottom point)
    m_target->DrawLine(
        D2D1::Point2F(cx, centerY - 40),
        D2D1::Point2F(cx, centerY + 48),
        m_brushNeonDim.Get(), 1.0f);

    // Shield boss — small circle at upper center (like a shield's center grip)
    D2D1_ELLIPSE boss = D2D1::Ellipse(D2D1::Point2F(cx, centerY - 18), 6, 6);
    m_target->FillEllipse(boss, m_brushNeon.Get());
    D2D1_ELLIPSE bossInner = D2D1::Ellipse(D2D1::Point2F(cx, centerY - 18), 3.5f, 3.5f);
    m_target->FillEllipse(bossInner, m_brushNeonBright.Get());

    // Diagonal accent lines (heraldic style) from boss to corners
    m_target->DrawLine(
        D2D1::Point2F(cx - 4, centerY - 15),
        D2D1::Point2F(cx - 24, centerY + 20),
        m_brushNeonDim.Get(), 0.8f);
    m_target->DrawLine(
        D2D1::Point2F(cx + 4, centerY - 15),
        D2D1::Point2F(cx + 24, centerY + 20),
        m_brushNeonDim.Get(), 0.8f);

    // Glossy highlight on upper left (keeps the EVE aesthetic)
    D2D1_ELLIPSE hl = D2D1::Ellipse(D2D1::Point2F(cx - 13, centerY - 16), 7, 18);
    m_target->FillEllipse(hl, m_brushWhiteLight.Get());
    D2D1_ELLIPSE hl2 = D2D1::Ellipse(D2D1::Point2F(cx - 16, centerY - 22), 3.5f, 9);
    m_target->FillEllipse(hl2, m_brushWhiteLight.Get());
}

// A single serious green eye — narrow, flat horizontal slit.
// No frown angle, no big round shapes, just a focused stern gaze.
void RobotRenderer::DrawSeriousEye(float ex, float ey, bool left) {
    (void)left; // both eyes are identical, left flag only kept for signature

    float halfW = 7.5f;    // slightly wide
    float halfH = 1.8f;    // very narrow slit

    // Outer red eye shape
    D2D1_ELLIPSE eye = D2D1::Ellipse(D2D1::Point2F(ex, ey), halfW, halfH);
    m_target->FillEllipse(eye, m_brushCape.Get());

    // Inner brighter red core
    D2D1_ELLIPSE inner = D2D1::Ellipse(D2D1::Point2F(ex, ey - halfH * 0.1f), halfW * 0.55f, halfH * 0.55f);
    m_target->FillEllipse(inner, m_brushCapeShade.Get());

    // Tiny white spark
    D2D1_ELLIPSE core = D2D1::Ellipse(D2D1::Point2F(ex - 1.0f, ey - halfH * 0.2f), halfW * 0.18f, halfH * 0.4f);
    m_target->FillEllipse(core, m_brushSpark.Get());
}

// Golden Spartan helmet head with serious flat green eyes.
// `sleeping` overrides with closed eye lines.
// `turnOffsetX` shifts the eyes sideways to "look ahead".
void RobotRenderer::DrawHead(float cx, float headY, EyeExpression expr, bool sleeping, float turnOffsetX, bool showVisor) {
    // 1. Shadow offset (drop shadow for depth)
    FillHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 1.05f, 1.5f, 1.5f, m_brushWhiteShade.Get());
    // 2. Main gold helmet body
    FillHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 1.0f, 0.0f, 0.0f, m_brushWhite.Get());
    // 3. Right side mid-tone shading
    FillHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 0.92f, 5.0f, 0.0f, m_brushWhiteMid.Get());
    // 4. Right edge deeper shade
    FillHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 0.78f, 8.0f, 0.0f, m_brushWhiteShade.Get());
    // 5. Blend left side back to gold
    FillHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 0.90f, -3.0f, 0.0f, m_brushWhite.Get());

    // Metallic highlight on dome (upper left)
    D2D1_ELLIPSE hl = D2D1::Ellipse(D2D1::Point2F(cx - 10, headY - 16), 5, 8);
    m_target->FillEllipse(hl, m_brushWhiteLight.Get());

    // Dark gold outline / rim
    StrokeHelmetPath(m_factory.Get(), m_target.Get(), cx, headY, 1.0f, 0.0f, 0.0f,
                     m_brushGoldDark.Get(), 1.5f);

    // Nose guard — raised central ridge from brow to chin
    ComPtr<ID2D1PathGeometry> noseGeo;
    m_factory->CreatePathGeometry(noseGeo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> noseSink;
    noseGeo->Open(noseSink.GetAddressOf());
    noseSink->BeginFigure(
        D2D1::Point2F(cx - 3, headY - 16), D2D1_FIGURE_BEGIN_FILLED);
    noseSink->AddBezier(D2D1::BezierSegment(
        D2D1::Point2F(cx - 4, headY - 8),
        D2D1::Point2F(cx - 2, headY + 10),
        D2D1::Point2F(cx - 1, headY + 22)));
    noseSink->AddLine(D2D1::Point2F(cx + 1, headY + 22));
    noseSink->AddBezier(D2D1::BezierSegment(
        D2D1::Point2F(cx + 2, headY + 10),
        D2D1::Point2F(cx + 4, headY - 8),
        D2D1::Point2F(cx + 3, headY - 16)));
    noseSink->EndFigure(D2D1_FIGURE_END_CLOSED);
    noseSink->Close();
    m_target->FillGeometry(noseGeo.Get(), m_brushGoldMid.Get());
    m_target->DrawGeometry(noseGeo.Get(), m_brushGoldDark.Get(), 1.0f);

    // Cheek guard accents — curved lines on each side
    m_target->DrawLine(
        D2D1::Point2F(cx - 18, headY - 6),
        D2D1::Point2F(cx - 20, headY + 14),
        m_brushGoldDark.Get(), 1.2f);
    m_target->DrawLine(
        D2D1::Point2F(cx + 18, headY - 6),
        D2D1::Point2F(cx + 20, headY + 14),
        m_brushGoldDark.Get(), 1.2f);

    // Brow ridge line across the face
    m_target->DrawLine(
        D2D1::Point2F(cx - 20, headY - 8),
        D2D1::Point2F(cx + 20, headY - 8),
        m_brushGoldDark.Get(), 1.0f);

    // Eyes position
    float fx = cx + turnOffsetX;
    float eyeY = headY - 3;

    if (sleeping) {
        m_target->DrawLine(D2D1::Point2F(fx - 11, eyeY), D2D1::Point2F(fx - 3, eyeY), m_brushCape.Get(), 1.5f);
        m_target->DrawLine(D2D1::Point2F(fx + 3, eyeY), D2D1::Point2F(fx + 11, eyeY), m_brushCape.Get(), 1.5f);
        return;
    }

    // Always serious / frowning green eyes
    DrawSeriousEye(fx - 8, eyeY, true);
    DrawSeriousEye(fx + 8, eyeY, false);

    // Helmet rivets — small dark gold dots on the sides
    D2D1_ELLIPSE rivetL = D2D1::Ellipse(D2D1::Point2F(cx - 22, headY + 5), 2, 2);
    m_target->FillEllipse(rivetL, m_brushGoldDark.Get());
    D2D1_ELLIPSE rivetR = D2D1::Ellipse(D2D1::Point2F(cx + 22, headY + 5), 2, 2);
    m_target->FillEllipse(rivetR, m_brushGoldDark.Get());

    // Chin guard line
    m_target->DrawLine(
        D2D1::Point2F(cx - 18, headY + 16),
        D2D1::Point2F(cx + 18, headY + 16),
        m_brushGoldDark.Get(), 0.8f);
}

// EVE's arms: slim leaf/fin shapes that float beside the body with a
// constant gap. `leanDeg` sweeps both arms backward together with the
// body while moving. `dislocate` pops the arm further out of its resting
// spot — used for the "say hi" wave, since her parts are magnetically
// detached and can move freely rather than just rotate in place.
void RobotRenderer::DrawArm(float cx, float cy, float bob, bool left, bool waving, float waveAngle,
                             float leanDeg, float dislocate, float squashX) {
    float armHalfW = 7.0f;
    float armHalfH = 32.0f;
    float gap = -4.0f; // Negative gap: arms overlap body edge (connected)
    float bodyHalfW = 32.0f;

    float restX = cx + (left ? -1.0f : 1.0f) * (bodyHalfW + gap + armHalfW);
    float restY = cy + 6.0f + bob;

    // Pop the arm outward and upward when dislocated (mid-wave)
    float baseX = restX + (left ? -1.0f : 1.0f) * 16.0f * dislocate;
    float baseY = restY - 12.0f * dislocate;

    float angleDeg = 0.0f;
    if (waving && !left) angleDeg += 34.0f * sinf(waveAngle);
    angleDeg += leanDeg;

    bool transformed = fabsf(angleDeg) > 0.01f || fabsf(squashX - 1.0f) > 0.001f;
    D2D1_POINT_2F pivot = D2D1::Point2F(cx + (left ? -1.0f : 1.0f) * bodyHalfW * 0.5f, cy - 18 + bob);
    if (transformed) {
        D2D1::Matrix3x2F squash = D2D1::Matrix3x2F::Scale(D2D1::SizeF(squashX, 1.0f), pivot);
        D2D1::Matrix3x2F rot = D2D1::Matrix3x2F::Rotation(angleDeg, pivot);
        m_target->SetTransform(squash * rot);
    }

    // Arm body — main fill
    D2D1_ELLIPSE arm = D2D1::Ellipse(D2D1::Point2F(baseX, baseY), armHalfW, armHalfH);
    m_target->FillEllipse(arm, m_brushWhite.Get());

    // Shading
    float shadeX = baseX + (left ? -2.0f : 2.0f);
    D2D1_ELLIPSE shade = D2D1::Ellipse(D2D1::Point2F(shadeX, baseY), armHalfW - 2.0f, armHalfH - 5.0f);
    m_target->FillEllipse(shade, m_brushWhiteMid.Get());

    // Highlight
    float hlX = baseX + (left ? 2.0f : -2.0f);
    D2D1_ELLIPSE hl = D2D1::Ellipse(D2D1::Point2F(hlX, baseY - 6.0f), armHalfW - 3.5f, armHalfH - 12.0f);
    m_target->FillEllipse(hl, m_brushWhiteLight.Get());

    if (transformed) {
        m_target->SetTransform(D2D1::Matrix3x2F::Identity());
    }

    // Shoulder joint — small neon circle where arm meets body
    float shoulderX = cx + (left ? -1.0f : 1.0f) * (bodyHalfW - 2.0f);
    float shoulderY = cy - 18 + bob;
    D2D1_ELLIPSE shoulder = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 4.5f, 4.5f);
    m_target->FillEllipse(shoulder, m_brushNeon.Get());
    D2D1_ELLIPSE shoulderInner = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 2.5f, 2.5f);
    m_target->FillEllipse(shoulderInner, m_brushNeonBright.Get());
}

void RobotRenderer::DrawPlantSymbol(float cx, float cy) {
    float symY = cy - 6;
    D2D1_ELLIPSE glow = D2D1::Ellipse(D2D1::Point2F(cx, symY), 6.5f, 6.5f);
    m_target->FillEllipse(glow, m_brushPlant.Get());
    D2D1_ELLIPSE center = D2D1::Ellipse(D2D1::Point2F(cx, symY), 4.5f, 4.5f);
    m_target->FillEllipse(center, m_brushBlack.Get());
    D2D1_ELLIPSE leaf = D2D1::Ellipse(D2D1::Point2F(cx, symY - 0.5f), 2.5f, 3.5f);
    m_target->FillEllipse(leaf, m_brushPlant.Get());
    D2D1_ELLIPSE dot = D2D1::Ellipse(D2D1::Point2F(cx, symY), 1.0f, 1.0f);
    m_target->FillEllipse(dot, m_brushWhiteLight.Get());
}

void RobotRenderer::DrawGear(float cx, float cy, float r) {
    D2D1_ELLIPSE gear = D2D1::Ellipse(D2D1::Point2F(cx, cy), r, r);
    m_target->FillEllipse(gear, m_brushWhiteMid.Get());
    D2D1_ELLIPSE inner = D2D1::Ellipse(D2D1::Point2F(cx, cy), r * 0.5f, r * 0.5f);
    m_target->FillEllipse(inner, m_brushBlack.Get());
    D2D1_ELLIPSE dot = D2D1::Ellipse(D2D1::Point2F(cx, cy), r * 0.2f, r * 0.2f);
    m_target->FillEllipse(dot, m_brushNeon.Get());
}

void RobotRenderer::DrawSpinningArms(float cx, float cy, float bob, float spinAngle) {
    float armHalfW = 6.5f;
    float armHalfH = 20.0f;
    float orbitR = 42.0f;

    float angle1 = spinAngle * 3.14159265f / 180.0f;
    float ax1 = cx + orbitR * cosf(angle1);
    float ay1 = cy + bob + orbitR * 0.6f * sinf(angle1);

    D2D1_ELLIPSE a1 = D2D1::Ellipse(D2D1::Point2F(ax1, ay1), armHalfW, armHalfH);
    m_target->FillEllipse(a1, m_brushWhite.Get());
    D2D1_ELLIPSE a1s = D2D1::Ellipse(D2D1::Point2F(ax1 + 2, ay1), armHalfW - 2, armHalfH - 5);
    m_target->FillEllipse(a1s, m_brushWhiteMid.Get());

    float angle2 = angle1 + 3.14159265f;
    float ax2 = cx + orbitR * cosf(angle2);
    float ay2 = cy + bob + orbitR * 0.6f * sinf(angle2);
    D2D1_ELLIPSE a2 = D2D1::Ellipse(D2D1::Point2F(ax2, ay2), armHalfW, armHalfH);
    m_target->FillEllipse(a2, m_brushWhite.Get());
    D2D1_ELLIPSE a2s = D2D1::Ellipse(D2D1::Point2F(ax2 + 2, ay2), armHalfW - 2, armHalfH - 5);
    m_target->FillEllipse(a2s, m_brushWhiteMid.Get());
}

// Red cape flowing behind the body with wind animation.
// The cape sways dynamically using sine waves on multiple frequencies
// to simulate realistic wind blowing from the side.
// `leanDeg` tilts the cape with body movement for dynamic flow.
void RobotRenderer::DrawCape(float cx, float cy, float bob, float leanDeg) {
    float centerY = cy + bob;
    float t = m_animTime;

    // Wind animation — multi-frequency sine waves for organic motion
    // Primary wind: slow sway. Secondary: faster flutter. Tertiary: edge ripple.
    float wind1 = sinf(t * 1.8f * (float)M_PI);          // slow main sway
    float wind2 = sinf(t * 4.5f * (float)M_PI + 0.7f);   // faster flutter
    float wind3 = sinf(t * 7.0f * (float)M_PI + 1.3f);   // edge ripple

    // Wind affects different parts of the cape differently:
    // Top (near shoulders) barely moves, bottom hem moves most
    float topSway    = wind1 * 2.0f;
    float midSway    = wind1 * 6.0f + wind2 * 2.0f;
    float bottomSway = wind1 * 12.0f + wind2 * 5.0f + wind3 * 3.0f;
    float hemFlutter = wind2 * 4.0f + wind3 * 6.0f;

    bool transformed = fabsf(leanDeg) > 0.01f;
    D2D1_POINT_2F pivot = D2D1::Point2F(cx, centerY - 20);
    if (transformed) {
        m_target->SetTransform(D2D1::Matrix3x2F::Rotation(leanDeg * 0.6f, pivot));
    }

    // === Shadow layer (offset, darker) ===
    ComPtr<ID2D1PathGeometry> geo;
    m_factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + x, centerY + y);
    };

    // Shadow cape — slightly larger, offset
    sink->BeginFigure(pt(-26 + topSway, -30), D2D1_FIGURE_BEGIN_FILLED);
    sink->AddBezier(D2D1::BezierSegment(
        pt(-40 + midSway, -5),
        pt(-38 + bottomSway, 25),
        pt(-32 + bottomSway + hemFlutter, 50)));
    sink->AddBezier(D2D1::BezierSegment(
        pt(-22 + hemFlutter, 58 + wind3 * 3),
        pt(22 - hemFlutter, 58 + wind3 * 3),
        pt(32 + bottomSway - hemFlutter, 50)));
    sink->AddBezier(D2D1::BezierSegment(
        pt(38 + bottomSway, 25),
        pt(40 + midSway, -5),
        pt(26 + topSway, -30)));
    sink->AddBezier(D2D1::BezierSegment(
        pt(15 + topSway * 0.5f, -32),
        pt(-15 + topSway * 0.5f, -32),
        pt(-26 + topSway, -30)));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();
    m_target->FillGeometry(geo.Get(), m_brushCapeShade.Get());

    // === Main cape fill (slightly smaller, pure red) ===
    ComPtr<ID2D1PathGeometry> geo2;
    m_factory->CreatePathGeometry(geo2.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink2;
    geo2->Open(sink2.GetAddressOf());

    sink2->BeginFigure(pt(-24 + topSway, -28), D2D1_FIGURE_BEGIN_FILLED);
    sink2->AddBezier(D2D1::BezierSegment(
        pt(-36 + midSway, -3),
        pt(-34 + bottomSway, 23),
        pt(-28 + bottomSway + hemFlutter * 0.8f, 46)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt(-18 + hemFlutter * 0.8f, 53 + wind3 * 2),
        pt(18 - hemFlutter * 0.8f, 53 + wind3 * 2),
        pt(28 + bottomSway - hemFlutter * 0.8f, 46)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt(34 + bottomSway, 23),
        pt(36 + midSway, -3),
        pt(24 + topSway, -28)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt(14 + topSway * 0.5f, -30),
        pt(-14 + topSway * 0.5f, -30),
        pt(-24 + topSway, -28)));
    sink2->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink2->Close();
    m_target->FillGeometry(geo2.Get(), m_brushCape.Get());

    // === Animated fold lines — sway with the wind ===
    float fold1X = cx - 15 + midSway * 0.3f;
    float fold2X = cx + 5 + midSway * 0.2f;
    float fold3X = cx + 18 + midSway * 0.25f;

    m_target->DrawLine(
        D2D1::Point2F(fold1X, centerY - 15),
        D2D1::Point2F(fold1X - 3 + bottomSway * 0.3f, centerY + 40),
        m_brushCapeShade.Get(), 1.2f);
    m_target->DrawLine(
        D2D1::Point2F(fold2X, centerY - 20),
        D2D1::Point2F(fold2X - 2 + bottomSway * 0.2f, centerY + 45),
        m_brushCapeShade.Get(), 1.0f);
    m_target->DrawLine(
        D2D1::Point2F(fold3X, centerY - 12),
        D2D1::Point2F(fold3X + 2 + bottomSway * 0.25f, centerY + 38),
        m_brushCapeShade.Get(), 1.0f);

    // === Neon trim along the bottom hem — follows the flutter ===
    float hemLeftX  = cx - 28 + bottomSway + hemFlutter * 0.8f;
    float hemRightX = cx + 28 + bottomSway - hemFlutter * 0.8f;
    float hemY      = centerY + 46 + wind3 * 2;
    m_target->DrawLine(
        D2D1::Point2F(hemLeftX, hemY),
        D2D1::Point2F(hemRightX, hemY),
        m_brushNeon.Get(), 1.0f);

    if (transformed) {
        m_target->SetTransform(D2D1::Matrix3x2F::Identity());
    }
}

// Spartan crest — a narrow red horsehair plume flowing straight back from the
// crown of the helmet. Drawn as a vertical path so it stays aligned with the
// back of the head and is not affected by the head's rotation.
void RobotRenderer::DrawSpartanCrest(float cx, float headY) {
    // Crest base at the crown, flows up (negative Y) to trail behind the head
    float baseY = headY - 26;

    // Animate the plume trailing in the wind
    float t = m_animTime;
    float wind1 = sinf(t * 1.5f * (float)M_PI) * 1.5f;
    float wind2 = sinf(t * 3.5f * (float)M_PI + 0.6f) * 2.5f;

    // Crest path: narrow at the crown, widening slightly, then tapering
    // It flows straight back along the Y axis (up on screen)
    ComPtr<ID2D1PathGeometry> geo;
    m_factory->CreatePathGeometry(geo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink;
    geo->Open(sink.GetAddressOf());

    auto pt = [&](float x, float y) {
        return D2D1::Point2F(cx + x, baseY + y);
    };

    // Plume outline — starts at the crown, flows straight back
    float tipX = wind1 + wind2 * 0.3f;
    float midX = wind1 * 0.6f;
    float halfW = 4.0f;        // very narrow overall width
    float plumeLen = 40.0f;    // long plume trailing back

    sink->BeginFigure(pt(-halfW, 0), D2D1_FIGURE_BEGIN_FILLED);
    // Left edge flowing up to the left tip (with wind)
    sink->AddBezier(D2D1::BezierSegment(
        pt(-halfW - 1, -plumeLen * 0.35f),
        pt(-halfW - 2 + midX, -plumeLen * 0.7f),
        pt(-halfW * 0.5f + tipX, -plumeLen)));
    // Tip across the top
    sink->AddBezier(D2D1::BezierSegment(
        pt(tipX * 0.2f, -plumeLen - 4),
        pt(tipX * 0.5f, -plumeLen - 4),
        pt(halfW * 0.5f + tipX, -plumeLen)));
    // Right edge flowing back down to the crown
    sink->AddBezier(D2D1::BezierSegment(
        pt(halfW + 2 + midX, -plumeLen * 0.7f),
        pt(halfW + 1, -plumeLen * 0.35f),
        pt(halfW, 0)));
    // Crown base across
    sink->AddBezier(D2D1::BezierSegment(
        pt(halfW * 0.5f, 2),
        pt(-halfW * 0.5f, 2),
        pt(-halfW, 0)));
    sink->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink->Close();

    m_target->FillGeometry(geo.Get(), m_brushCapeShade.Get());

    // Inner plume (brighter red, slightly smaller)
    ComPtr<ID2D1PathGeometry> geo2;
    m_factory->CreatePathGeometry(geo2.GetAddressOf());
    ComPtr<ID2D1GeometrySink> sink2;
    geo2->Open(sink2.GetAddressOf());

    auto pt2 = [&](float x, float y) {
        return D2D1::Point2F(cx + x, baseY + y);
    };

    halfW = 2.2f;
    plumeLen = 36.0f;
    sink2->BeginFigure(pt2(-halfW, 0), D2D1_FIGURE_BEGIN_FILLED);
    sink2->AddBezier(D2D1::BezierSegment(
        pt2(-halfW - 0.5f, -plumeLen * 0.35f),
        pt2(-halfW - 1.0f + midX, -plumeLen * 0.7f),
        pt2(-halfW * 0.4f + tipX, -plumeLen)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt2(tipX * 0.15f, -plumeLen - 3),
        pt2(tipX * 0.4f, -plumeLen - 3),
        pt2(halfW * 0.4f + tipX, -plumeLen)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt2(halfW + 1.0f + midX, -plumeLen * 0.7f),
        pt2(halfW + 0.5f, -plumeLen * 0.35f),
        pt2(halfW, 0)));
    sink2->AddBezier(D2D1::BezierSegment(
        pt2(halfW * 0.4f, 1.5f),
        pt2(-halfW * 0.4f, 1.5f),
        pt2(-halfW, 0)));
    sink2->EndFigure(D2D1_FIGURE_END_CLOSED);
    sink2->Close();

    m_target->FillGeometry(geo2.Get(), m_brushCape.Get());

    // Plume texture / fold lines running back
    for (int i = 0; i < 5; i++) {
        float progress = (float)i / 5.0f;
        float lineY = -plumeLen * progress - 3;
        float waveX = sinf(t * 2.0f * (float)M_PI + progress * 3.0f) * (progress * 1.5f);
        m_target->DrawLine(
            D2D1::Point2F(cx - 1.5f + waveX, baseY + lineY),
            D2D1::Point2F(cx + 1.5f + waveX, baseY + lineY),
            m_brushCapeShade.Get(), 0.6f);
    }
}

// Electric arc between the head and body — jagged cyan lightning bolts
// that animate dynamically, simulating energy flowing through the neck.
void RobotRenderer::DrawElectricArc(float cx, float neckY, float bodyY) {
    float t = m_animTime;
    float gap = bodyY - neckY;
    if (gap < 2.0f) return;

    // Draw 3 jagged lightning bolts with different phases
    for (int bolt = 0; bolt < 3; bolt++) {
        float phase = t * 8.0f * (float)M_PI + bolt * 2.1f;
        float baseOffset = (bolt - 1) * 4.0f; // spread bolts across neck width

        // Flicker — bolt appears/disappears rapidly
        float flicker = sinf(phase + t * 15.0f);
        if (flicker < -0.3f) continue; // skip this frame for this bolt

        float alpha = 0.5f + 0.5f * flicker;
        m_brushElectric->SetOpacity(alpha);

        // Jagged path from head bottom to body top
        ComPtr<ID2D1PathGeometry> geo;
        m_factory->CreatePathGeometry(geo.GetAddressOf());
        ComPtr<ID2D1GeometrySink> sink;
        geo->Open(sink.GetAddressOf());

        int numSegments = 5;
        sink->BeginFigure(
            D2D1::Point2F(cx + baseOffset, neckY),
            D2D1_FIGURE_BEGIN_HOLLOW);

        for (int i = 1; i <= numSegments; i++) {
            float progress = (float)i / numSegments;
            float y = neckY + gap * progress;
            // Jagged X offset — random-looking but deterministic from sine
            float jagX = sinf(phase + i * 1.7f) * 6.0f +
                         sinf(phase * 2.3f + i * 3.1f) * 3.0f;
            // Last segment converges to body center
            if (i == numSegments) jagX = 0;
            sink->AddLine(D2D1::Point2F(cx + baseOffset + jagX, y));
        }

        sink->EndFigure(D2D1_FIGURE_END_OPEN);
        sink->Close();

        // Draw the bolt — thicker glow layer then sharp core
        m_brushElectric->SetOpacity(alpha * 0.3f);
        m_target->DrawGeometry(geo.Get(), m_brushElectric.Get(), 3.0f);
        m_brushElectric->SetOpacity(alpha);
        m_target->DrawGeometry(geo.Get(), m_brushElectric.Get(), 1.2f);

        // Small spark dots at endpoints
        D2D1_ELLIPSE sparkTop = D2D1::Ellipse(
            D2D1::Point2F(cx + baseOffset, neckY), 2.5f, 2.5f);
        m_target->FillEllipse(sparkTop, m_brushElectric.Get());
        D2D1_ELLIPSE sparkBot = D2D1::Ellipse(
            D2D1::Point2F(cx, bodyY), 2.5f, 2.5f);
        m_target->FillEllipse(sparkBot, m_brushElectric.Get());
    }

    m_brushElectric->SetOpacity(1.0f);
}

// Electric lightning effect around the entire robot body when executing tools.
// Multiple jagged bolts flicker around the silhouette at random angles.
void RobotRenderer::DrawToolLightning(float cx, float cy, float bob) {
    float t = m_animTime;
    float centerY = cy + bob;

    // Body bounding radius (approximate)
    float bodyW = 42.0f;
    float bodyH = 70.0f;

    // Draw 8 lightning bolts at different angles around the body
    for (int bolt = 0; bolt < 8; bolt++) {
        float angle = (bolt / 8.0f) * 2.0f * (float)M_PI + t * 0.5f;
        float phase = t * 12.0f * (float)M_PI + bolt * 1.7f;

        // Flicker — bolt appears/disappears rapidly
        float flicker = sinf(phase + t * 20.0f);
        if (flicker < -0.2f) continue;

        float alpha = 0.4f + 0.6f * flicker;

        // Start point: just outside body silhouette
        float startR = bodyW + 4.0f;
        float sx = cx + startR * cosf(angle);
        float sy = centerY + startR * 0.7f * sinf(angle);

        // End point: further out, jagged path
        float endR = bodyW + 18.0f + 6.0f * sinf(phase * 1.3f);
        float ex = cx + endR * cosf(angle);
        float ey = centerY + endR * 0.7f * sinf(angle);

        // Build jagged lightning path
        ComPtr<ID2D1PathGeometry> geo;
        m_factory->CreatePathGeometry(geo.GetAddressOf());
        ComPtr<ID2D1GeometrySink> sink;
        geo->Open(sink.GetAddressOf());

        int numSegments = 4;
        sink->BeginFigure(D2D1::Point2F(sx, sy), D2D1_FIGURE_BEGIN_HOLLOW);

        for (int i = 1; i <= numSegments; i++) {
            float progress = (float)i / numSegments;
            // Interpolate from start to end
            float baseX = sx + (ex - sx) * progress;
            float baseY = sy + (ey - sy) * progress;
            // Perpendicular jag offset
            float perpX = -(ey - sy);
            float perpY = (ex - sx);
            float perpLen = sqrtf(perpX * perpX + perpY * perpY) + 0.001f;
            perpX /= perpLen;
            perpY /= perpLen;
            float jag = sinf(phase + i * 2.3f) * 5.0f + sinf(phase * 1.7f + i * 4.1f) * 3.0f;
            if (i == numSegments) jag = 0; // converge at end
            sink->AddLine(D2D1::Point2F(baseX + perpX * jag, baseY + perpY * jag));
        }

        sink->EndFigure(D2D1_FIGURE_END_OPEN);
        sink->Close();

        // Draw glow layer then sharp core
        m_brushElectric->SetOpacity(alpha * 0.25f);
        m_target->DrawGeometry(geo.Get(), m_brushElectric.Get(), 4.0f);
        m_brushElectric->SetOpacity(alpha);
        m_target->DrawGeometry(geo.Get(), m_brushElectric.Get(), 1.5f);

        // Spark dot at the outer endpoint
        D2D1_ELLIPSE spark = D2D1::Ellipse(D2D1::Point2F(ex, ey), 2.0f, 2.0f);
        m_brushElectric->SetOpacity(alpha);
        m_target->FillEllipse(spark, m_brushElectric.Get());
    }

    // Additional crackling sparks around the body
    for (int i = 0; i < 6; i++) {
        float sparkPhase = t * 15.0f * (float)M_PI + i * 1.9f;
        float sparkFlicker = sinf(sparkPhase + t * 25.0f);
        if (sparkFlicker < 0.3f) continue;

        float sparkAngle = i * 1.04f + t * 0.8f;
        float sparkR = bodyW + 8.0f + 4.0f * sinf(sparkPhase * 2.0f);
        float spX = cx + sparkR * cosf(sparkAngle);
        float spY = centerY + sparkR * 0.7f * sinf(sparkAngle);

        float alpha = 0.5f + 0.5f * sparkFlicker;
        m_brushElectric->SetOpacity(alpha);
        D2D1_ELLIPSE spark = D2D1::Ellipse(D2D1::Point2F(spX, spY), 1.5f, 1.5f);
        m_target->FillEllipse(spark, m_brushElectric.Get());
    }

    m_brushElectric->SetOpacity(1.0f);
}

// Shield on the left arm — a golden Spartan aspis (round shield)
void RobotRenderer::DrawShield(float cx, float cy, float bob, float leanDeg, float squashX) {
    float bodyHalfW = 32.0f;
    float gap = -4.0f;
    float shieldR = 34.0f;
    float restX = cx + (-1.0f) * (bodyHalfW + gap + shieldR * 0.6f);
    float restY = cy - 12.0f + bob;

    bool transformed = fabsf(leanDeg) > 0.01f || fabsf(squashX - 1.0f) > 0.001f;
    D2D1_POINT_2F pivot = D2D1::Point2F(cx - bodyHalfW * 0.5f, cy - 18 + bob);
    if (transformed) {
        D2D1::Matrix3x2F squash = D2D1::Matrix3x2F::Scale(D2D1::SizeF(squashX, 1.0f), pivot);
        D2D1::Matrix3x2F rot = D2D1::Matrix3x2F::Rotation(leanDeg, pivot);
        m_target->SetTransform(squash * rot);
    }

    // Shield outer rim — dark gold
    D2D1_ELLIPSE outer = D2D1::Ellipse(D2D1::Point2F(restX, restY), shieldR, shieldR);
    m_target->FillEllipse(outer, m_brushGoldDark.Get());

    // Shield main body — gold
    D2D1_ELLIPSE main = D2D1::Ellipse(D2D1::Point2F(restX, restY), shieldR - 2.5f, shieldR - 2.5f);
    m_target->FillEllipse(main, m_brushGold.Get());

    // Shield mid shade
    D2D1_ELLIPSE mid = D2D1::Ellipse(D2D1::Point2F(restX + 2.0f, restY + 2.0f), shieldR - 5.0f, shieldR - 5.0f);
    m_target->FillEllipse(mid, m_brushGoldMid.Get());

    // Shield highlight
    D2D1_ELLIPSE hl = D2D1::Ellipse(D2D1::Point2F(restX - 4.0f, restY - 5.0f), shieldR - 10.0f, shieldR - 10.0f);
    m_target->FillEllipse(hl, m_brushGoldLight.Get());

    // Shield boss (center stud) — neon blue
    D2D1_ELLIPSE boss = D2D1::Ellipse(D2D1::Point2F(restX, restY), 5.0f, 5.0f);
    m_target->FillEllipse(boss, m_brushNeon.Get());
    D2D1_ELLIPSE bossInner = D2D1::Ellipse(D2D1::Point2F(restX, restY), 3.0f, 3.0f);
    m_target->FillEllipse(bossInner, m_brushNeonBright.Get());

    // Lambda symbol (Spartan) in center — simple inverted V
    ComPtr<ID2D1PathGeometry> lambdaGeo;
    m_factory->CreatePathGeometry(lambdaGeo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> lambdaSink;
    lambdaGeo->Open(lambdaSink.GetAddressOf());
    lambdaSink->BeginFigure(D2D1::Point2F(restX - 6, restY + 6), D2D1_FIGURE_BEGIN_HOLLOW);
    lambdaSink->AddLine(D2D1::Point2F(restX, restY - 5));
    lambdaSink->AddLine(D2D1::Point2F(restX + 6, restY + 6));
    lambdaSink->EndFigure(D2D1_FIGURE_END_OPEN);
    lambdaSink->Close();
    m_brushNeonBright->SetOpacity(0.8f);
    m_target->DrawGeometry(lambdaGeo.Get(), m_brushNeonBright.Get(), 1.5f);
    m_brushNeonBright->SetOpacity(1.0f);

    if (transformed) {
        m_target->SetTransform(D2D1::Matrix3x2F::Identity());
    }

    // Shoulder joint
    float shoulderX = cx - (bodyHalfW - 2.0f);
    float shoulderY = cy - 18 + bob;
    D2D1_ELLIPSE shoulder = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 4.5f, 4.5f);
    m_target->FillEllipse(shoulder, m_brushNeon.Get());
    D2D1_ELLIPSE shoulderInner = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 2.5f, 2.5f);
    m_target->FillEllipse(shoulderInner, m_brushNeonBright.Get());
}

// Sword on the right arm — a golden Spartan xiphos (short sword)
void RobotRenderer::DrawSword(float cx, float cy, float bob, bool waving, float waveAngle,
                               float leanDeg, float dislocate, float squashX) {
    float bodyHalfW = 32.0f;
    float gap = -4.0f;
    float armHalfW = 7.0f;
    float restX = cx + (1.0f) * (bodyHalfW + gap + armHalfW);
    float restY = cy + 6.0f + bob;

    // Pop outward when dislocated (waving)
    float baseX = restX + 16.0f * dislocate;
    float baseY = restY - 12.0f * dislocate;

    float angleDeg = 0.0f;
    if (waving) angleDeg += 34.0f * sinf(waveAngle);
    angleDeg += leanDeg;

    bool transformed = fabsf(angleDeg) > 0.01f || fabsf(squashX - 1.0f) > 0.001f;
    D2D1_POINT_2F pivot = D2D1::Point2F(cx + bodyHalfW * 0.5f, cy - 18 + bob);
    if (transformed) {
        D2D1::Matrix3x2F squash = D2D1::Matrix3x2F::Scale(D2D1::SizeF(squashX, 1.0f), pivot);
        D2D1::Matrix3x2F rot = D2D1::Matrix3x2F::Rotation(angleDeg, pivot);
        m_target->SetTransform(squash * rot);
    }

    // Short arm stub (golden, matching body)
    D2D1_ELLIPSE arm = D2D1::Ellipse(D2D1::Point2F(baseX, baseY), armHalfW, 16.0f);
    m_target->FillEllipse(arm, m_brushWhite.Get());
    D2D1_ELLIPSE armShade = D2D1::Ellipse(D2D1::Point2F(baseX + 2.0f, baseY), armHalfW - 2.0f, 12.0f);
    m_target->FillEllipse(armShade, m_brushWhiteMid.Get());

    // Sword handle — dark gold
    float handleTopY = baseY - 16.0f;
    float handleBotY = baseY - 6.0f;
    D2D1_RECT_F handle = D2D1::RectF(baseX - 2.5f, handleTopY, baseX + 2.5f, handleBotY);
    m_target->FillRectangle(handle, m_brushGoldDark.Get());

    // Sword guard (crossbar) — gold
    D2D1_RECT_F guard = D2D1::RectF(baseX - 7.0f, handleTopY - 2.0f, baseX + 7.0f, handleTopY + 2.0f);
    m_target->FillRectangle(guard, m_brushGold.Get());

    // Sword pommel — gold sphere
    D2D1_ELLIPSE pommel = D2D1::Ellipse(D2D1::Point2F(baseX, handleBotY + 2.0f), 3.0f, 3.0f);
    m_target->FillEllipse(pommel, m_brushGold.Get());

    // Sword blade — pointed xiphos shape
    float bladeTopY = handleTopY - 2.0f;
    float bladeLen = 38.0f;
    ComPtr<ID2D1PathGeometry> bladeGeo;
    m_factory->CreatePathGeometry(bladeGeo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> bladeSink;
    bladeGeo->Open(bladeSink.GetAddressOf());
    bladeSink->BeginFigure(D2D1::Point2F(baseX - 3.0f, bladeTopY), D2D1_FIGURE_BEGIN_FILLED);
    bladeSink->AddLine(D2D1::Point2F(baseX + 3.0f, bladeTopY));
    bladeSink->AddLine(D2D1::Point2F(baseX, bladeTopY - bladeLen)); // pointed tip
    bladeSink->EndFigure(D2D1_FIGURE_END_CLOSED);
    bladeSink->Close();
    m_target->FillGeometry(bladeGeo.Get(), m_brushWhiteLight.Get(), nullptr);

    // Blade mid shade
    ComPtr<ID2D1PathGeometry> bladeMidGeo;
    m_factory->CreatePathGeometry(bladeMidGeo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> bladeMidSink;
    bladeMidGeo->Open(bladeMidSink.GetAddressOf());
    bladeMidSink->BeginFigure(D2D1::Point2F(baseX + 0.5f, bladeTopY), D2D1_FIGURE_BEGIN_FILLED);
    bladeMidSink->AddLine(D2D1::Point2F(baseX + 3.0f, bladeTopY));
    bladeMidSink->AddLine(D2D1::Point2F(baseX, bladeTopY - bladeLen));
    bladeMidSink->EndFigure(D2D1_FIGURE_END_CLOSED);
    bladeMidSink->Close();
    m_target->FillGeometry(bladeMidGeo.Get(), m_brushWhiteMid.Get(), nullptr);

    // Blade outline
    m_target->DrawGeometry(bladeGeo.Get(), m_brushGoldDark.Get(), 0.8f);

    // Blade center ridge line
    ComPtr<ID2D1PathGeometry> ridgeGeo;
    m_factory->CreatePathGeometry(ridgeGeo.GetAddressOf());
    ComPtr<ID2D1GeometrySink> ridgeSink;
    ridgeGeo->Open(ridgeSink.GetAddressOf());
    ridgeSink->BeginFigure(D2D1::Point2F(baseX, bladeTopY), D2D1_FIGURE_BEGIN_HOLLOW);
    ridgeSink->AddLine(D2D1::Point2F(baseX, bladeTopY - bladeLen));
    ridgeSink->EndFigure(D2D1_FIGURE_END_OPEN);
    ridgeSink->Close();
    m_target->DrawGeometry(ridgeGeo.Get(), m_brushGoldLight.Get(), 0.5f);

    if (transformed) {
        m_target->SetTransform(D2D1::Matrix3x2F::Identity());
    }

    // Shoulder joint
    float shoulderX = cx + (bodyHalfW - 2.0f);
    float shoulderY = cy - 18 + bob;
    D2D1_ELLIPSE shoulder = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 4.5f, 4.5f);
    m_target->FillEllipse(shoulder, m_brushNeon.Get());
    D2D1_ELLIPSE shoulderInner = D2D1::Ellipse(D2D1::Point2F(shoulderX, shoulderY), 2.5f, 2.5f);
    m_target->FillEllipse(shoulderInner, m_brushNeonBright.Get());
}

void RobotRenderer::DrawRobot() {
    D2D1_SIZE_F size = m_target->GetSize();
    float cx = size.width / 2;
    float cy = size.height / 2;
    float t = m_animTime;

    float bob = 4.0f * sinf(t * 1.5f * (float)M_PI);
    float headY = cy + bob - 74.0f;

    if (m_dragging) {
        float dBob = bob + 6.0f;
        float dHeadY = cy + dBob - 74.0f;
        DrawGroundShadow(cx, cy + dBob + 66, 36);
        DrawCape(cx, cy, dBob, 0);
        DrawEggBody(cx, cy, dBob);
        DrawElectricArc(cx, dHeadY + 22, cy + dBob - 44);
        DrawHead(cx, dHeadY, EyeExpression::Surprised, false, 0.0f, false);
        DrawSpartanCrest(cx, dHeadY);
        DrawShield(cx, cy, dBob);
        DrawSword(cx, cy, dBob);
        return;
    }

    switch (m_state) {
        case RobotState::Idle: {
            DrawGroundShadow(cx, cy + bob + 66, 44);
            DrawHoverGlow(cx, cy + bob + 66);
            DrawCape(cx, cy, bob, 0);
            DrawEggBody(cx, cy, bob);
            DrawElectricArc(cx, headY + 22, cy + bob - 44);
            DrawHead(cx, headY, m_eyeExpression, false);
            DrawSpartanCrest(cx, headY);
            DrawShield(cx, cy, bob);
            DrawSword(cx, cy, bob);
            DrawPlantSymbol(cx, cy + bob);
            break;
        }
        case RobotState::Spinning: {
            float sBob = 3.0f * sinf(t * 4.0f * (float)M_PI);
            // 2 full revolutions over m_spinDuration: angle = 720 deg * progress
            float progress = Clamp01(m_spinTimer / m_spinDuration);
            float spinAngle = 720.0f * progress;
            // Start from the side, spin outward
            spinAngle += m_facingRight ? 90.0f : 270.0f;

            DrawGroundShadow(cx, cy + sBob + 66, 42);
            DrawHoverGlow(cx, cy + sBob + 66);
            DrawCape(cx, cy, sBob, 0);
            DrawEggBody(cx, cy, sBob);
            DrawElectricArc(cx, cy + sBob - 74.0f + 22, cy + sBob - 44);
            DrawHead(cx, cy + sBob - 74.0f, EyeExpression::Surprised, false, 0.0f, false);
            DrawSpartanCrest(cx, cy + sBob - 74.0f);
            DrawSpinningArms(cx, cy, sBob, spinAngle);
            DrawPlantSymbol(cx, cy + sBob);
            break;
        }
        case RobotState::Walking: {
            float gBob = 6.0f * sinf(t * 2.0f * (float)M_PI);
            float gHeadY = cy + gBob - 74.0f;

            DrawGroundShadow(cx, cy + gBob + 66, 40);
            DrawHoverGlow(cx, cy + gBob + 66);

            // Lean the body + head into the direction of travel, like a
            // fast forward dash, then level out as EVE nears the target.
            float leanDeg = ComputeWalkLeanDeg();

            // Turn amount tracks the lean strength: strongest right as she
            // launches, easing back to a full frontal view as she arrives.
            float turnAmount = Clamp01(fabsf(leanDeg) / 75.0f);
            float bodyScaleX = 1.0f - 0.34f * turnAmount;   // squash = turning edge-on
            float faceOffsetX = 11.0f * turnAmount * (m_facingRight ? 1.0f : -1.0f);

            D2D1_POINT_2F pivot = D2D1::Point2F(cx, cy + gBob);
            D2D1::Matrix3x2F squash = D2D1::Matrix3x2F::Scale(D2D1::SizeF(bodyScaleX, 1.0f), pivot);
            D2D1::Matrix3x2F rot = D2D1::Matrix3x2F::Rotation(leanDeg, pivot);
            m_target->SetTransform(squash * rot);
            DrawCape(cx, cy, gBob, leanDeg);
            DrawEggBody(cx, cy, gBob);
            DrawElectricArc(cx, gHeadY + 22, cy + gBob - 44);
            DrawHead(cx, gHeadY, EyeExpression::Neutral, false, faceOffsetX, false);
            DrawSpartanCrest(cx, gHeadY);
            DrawPlantSymbol(cx, cy + gBob);
            m_target->SetTransform(D2D1::Matrix3x2F::Identity());

            // Arms trail slightly more than the body — a real twist, not
            // just a tilt, sweeping backward as she turns to look ahead.
            float armLean = leanDeg * 1.15f;
            float armScaleX = 1.0f - 0.22f * turnAmount;
            DrawShield(cx, cy, gBob, armLean, armScaleX);
            DrawSword(cx, cy, gBob, false, 0.0f, armLean, 0.0f, armScaleX);
            break;
        }
        case RobotState::Greeting: {
            float waveAngle = t * 6.0f * (float)M_PI;
            DrawGroundShadow(cx, cy + bob + 66, 44);
            DrawHoverGlow(cx, cy + bob + 66);
            DrawCape(cx, cy, bob, 0);
            DrawEggBody(cx, cy, bob);
            DrawElectricArc(cx, headY + 22, cy + bob - 44);
            DrawHead(cx, headY, EyeExpression::Happy, false);
            DrawSpartanCrest(cx, headY);

            // The waving hand pops out of its resting spot before settling
            // into the wave, then eases back in before returning to idle.
            float total = m_nextBehaviorTime;
            float dislocate;
            if (m_stateTimer < 0.22f) {
                dislocate = EaseOutQuad(Clamp01(m_stateTimer / 0.22f));
            } else if (m_stateTimer > total - 0.3f) {
                dislocate = SmoothStep(Clamp01((total - m_stateTimer) / 0.3f));
            } else {
                dislocate = 1.0f;
            }

            DrawShield(cx, cy, bob);
            DrawSword(cx, cy, bob, true, waveAngle, 0.0f, dislocate);
            DrawPlantSymbol(cx, cy + bob);
            break;
        }
        case RobotState::Working: {
            float wBob = 3.0f * sinf(t * 2.5f * (float)M_PI);
            float wHeadY = cy + wBob - 74.0f;
            DrawGroundShadow(cx, cy + wBob + 66, 42);
            DrawHoverGlow(cx, cy + wBob + 66);
            DrawCape(cx, cy, wBob, 0);
            DrawEggBody(cx, cy, wBob);
            DrawElectricArc(cx, wHeadY + 22, cy + wBob - 44);
            DrawHead(cx, wHeadY, EyeExpression::Curious, false);
            DrawSpartanCrest(cx, wHeadY);
            DrawShield(cx, cy - 10 + wBob, wBob);
            DrawSword(cx, cy - 10 + wBob, wBob);
            DrawPlantSymbol(cx, cy + wBob);
            break;
        }
        case RobotState::Celebrating: {
            float cBob = 5.0f * sinf(t * 3.0f * (float)M_PI);
            float cHeadY = cy + cBob - 74.0f;
            DrawGroundShadow(cx, cy + cBob + 66, 46);
            DrawHoverGlow(cx, cy + cBob + 66);
            DrawCape(cx, cy, cBob, 0);
            DrawEggBody(cx, cy, cBob);
            DrawElectricArc(cx, cHeadY + 22, cy + cBob - 44);
            DrawHead(cx, cHeadY, EyeExpression::Happy, false);
            DrawSpartanCrest(cx, cHeadY);
            DrawShield(cx, cy - 10 + cBob, cBob);
            DrawSword(cx, cy - 10 + cBob, cBob);
            DrawPlantSymbol(cx, cy + cBob);
            for (int i = 0; i < 6; i++) {
                float angle = (i / 6.0f) * 2.0f * (float)M_PI + t * 2;
                float dist = 40 + 8 * sinf(t * 5 * (float)M_PI + i);
                float sx = cx + dist * cosf(angle);
                float sy = cy + dist * sinf(angle);
                D2D1_ELLIPSE sp = D2D1::Ellipse(D2D1::Point2F(sx, sy), 3, 3);
                m_target->FillEllipse(sp, m_brushNeon.Get());
            }
            break;
        }
        case RobotState::Sleeping: {
            float sBob = 2.0f * sinf(t * 0.8f * (float)M_PI);
            float sHeadY = cy + sBob - 74.0f;
            DrawGroundShadow(cx, cy + sBob + 66, 40);
            DrawCape(cx, cy, sBob, 0);
            DrawEggBody(cx, cy, sBob);
            DrawElectricArc(cx, sHeadY + 22, cy + sBob - 44);
            DrawHead(cx, sHeadY, EyeExpression::Neutral, true);
            DrawSpartanCrest(cx, sHeadY);
            DrawShield(cx, cy, sBob);
            DrawSword(cx, cy, sBob);
            break;
        }
    }

    // Tool execution lightning effect: electric bolts around body
    if (m_executingTools) {
        DrawToolLightning(cx, cy, bob);
    }

    // Thinking overlay: floating dots above head while AI is processing
    if (m_thinking) {
        float thinkY = cy + bob - 100.0f;
        for (int i = 0; i < 3; i++) {
            float phase = t * 3.0f + i * 0.5f;
            float alpha = 0.5f + 0.5f * sinf(phase * (float)M_PI);
            float yOff = -6.0f * sinf(phase * (float)M_PI);
            float dotR = 3.0f + 1.5f * alpha;
            D2D1_ELLIPSE dot = D2D1::Ellipse(
                D2D1::Point2F(cx + (i - 1) * 12.0f, thinkY + yOff), dotR, dotR);
            D2D1::ColorF dotColor(0xFF00CFFF);
            dotColor.a = alpha;
            ComPtr<ID2D1SolidColorBrush> thinkBrush;
            m_target->CreateSolidColorBrush(dotColor, thinkBrush.GetAddressOf());
            m_target->FillEllipse(dot, thinkBrush.Get());
        }
    }
}
